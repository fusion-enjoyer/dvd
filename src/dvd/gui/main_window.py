"""Main window: top bar, step navigation, pages and the live disc budget bar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dvd import project as proj
from dvd.budget.planner import Plan
from dvd.build import estimate
from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.gui.pages import BuildPage, TracksPage
from dvd.gui.theme import DENSITY, stylesheet
from dvd.gui.video_editor import VideoEditor
from dvd.gui.widgets import BudgetBar, CompareWell, ModeSwitch
from dvd.probe import SourceInfo, probe
from dvd.probe.report import fps_text, size_text, timecode
from dvd.project.model import AudioProfile, ContentProfile, Project, ViewingProfile

VIDEO_SUFFIXES = {".mkv", ".m2ts", ".mts", ".mp4", ".m4v", ".ts", ".mov", ".avi", ".mpg"}

# Navigation per mode: (page key, label key). Simple mode merges some pages.
NAV = {
    "basit": [
        ("video", "nav.video"),
        ("picture", "nav.picture.simple"),
        ("audio", "nav.audio_subs"),
        ("menu", "nav.menu"),
        ("build", "nav.build"),
    ],
    "pro": [
        ("video", "nav.sources"),
        ("picture", "nav.titles"),
        ("audio", "nav.audio"),
        ("subs", "nav.subs"),
        ("chapters", "nav.chapters"),
        ("menu", "nav.menus"),
        ("disc", "nav.disc"),
        ("build", "nav.output"),
    ],
}
# Where a page lands when the mode changes and it has no counterpart.
FALLBACK = {"subs": "audio", "chapters": "video", "disc": "build"}


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def panel(name: str) -> QWidget:
    w = QWidget()
    w.setObjectName(name)
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    return w


def quality(plan: Plan) -> tuple[int, str]:
    kbps = plan.video_kbps
    if kbps >= 6500:
        return 4, t("quality.commercial")
    if kbps >= 4500:
        return 3, t("quality.good")
    return 2, t("quality.low")


class DropZone(QWidget):
    open_requested = Signal()
    project_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setProperty("active", False)
        box = QVBoxLayout(self)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(12)
        self.title = label(t("empty.title"), "heroTitle")
        self.body = label(t("empty.body"), "muted")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        open_file = QPushButton(t("empty.open"))
        open_file.setObjectName("primary")
        open_file.clicked.connect(self.open_requested)
        open_project = QPushButton(t("empty.open_project"))
        open_project.clicked.connect(self.project_requested)
        buttons.addWidget(open_file)
        buttons.addWidget(open_project)
        box.addWidget(self.title)
        box.addWidget(self.body)
        box.addSpacing(8)
        box.addLayout(buttons)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_busy(self, text: str | None) -> None:
        self.title.setText(text or t("empty.title"))


class VideoPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(24, 20, 24, 20)
        self.box.setSpacing(16)
        self.title = label(t("video.title"), "pageTitle")
        self.card = panel("card")
        self.card.setMaximumWidth(760)
        self.form = QFormLayout(self.card)
        self.form.setContentsMargins(18, 16, 18, 16)
        self.form.setHorizontalSpacing(24)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.box.addWidget(self.title)
        self.box.addWidget(self.card)
        self.box.addStretch()

    def show_source(self, info: SourceInfo) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        v = info.main_video

        def row(key: str, text: str, mono: bool = False) -> None:
            self.form.addRow(label(t(key), "muted"), label(text, "value" if mono else None, True))

        row("video.file", f"{info.path.name}  ({size_text(info.size)})")
        row("video.duration", timecode(info.duration), mono=True)
        if v:
            picture = f"{v.codec} {v.width}×{v.height}  {fps_text(v.fps)}  {v.color_matrix or ''}"
            row("video.picture", picture, mono=True)
        audio = [f"{a.language or '?'} · {a.profile or a.codec} {a.channels}ch" for a in info.audio]
        row("video.audio", "\n".join(audio) or t("video.none"))
        subs = [f"{s.language or '?'} · {s.codec}" for s in info.subtitles]
        row("video.subs", "\n".join(subs) or t("video.none"))
        row("video.chapters", str(len(info.chapters)) if info.chapters else t("video.none"))


class PicturePage(QWidget):
    profile_changed = Signal(str, str)  # field, value
    switch_to_pro = Signal()
    position_changed = Signal(float)  # 0..1 of the film
    frame_step = Signal(int)  # -1 or +1
    trial_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        center = QWidget()
        cbox = QVBoxLayout(center)
        cbox.setContentsMargins(16, 16, 16, 16)
        self.well = CompareWell()
        cbox.addWidget(self.well, 1)
        scrub = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(400)
        self.slider.sliderReleased.connect(
            lambda: self.position_changed.emit(self.slider.value() / 1000)
        )
        self.timecode = label("", "mono")
        self.step_buttons = []
        for delta, text, tip in ((-1, "‹", "picture.prev_frame"), (1, "›", "picture.next_frame")):
            b = QPushButton(text)
            b.setFixedWidth(32)
            b.setToolTip(t(tip))
            b.clicked.connect(lambda _=False, d=delta: self.frame_step.emit(d))
            self.step_buttons.append(b)
            key = Qt.Key.Key_Left if delta < 0 else Qt.Key.Key_Right
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda d=delta: self.frame_step.emit(d))
        scrub.addWidget(self.slider, 1)
        scrub.addWidget(self.step_buttons[0])
        scrub.addWidget(self.timecode)
        scrub.addWidget(self.step_buttons[1])
        cbox.addLayout(scrub)
        self.compare_row = QWidget()
        row = QHBoxLayout(self.compare_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.view_switch = ModeSwitch(
            {"a": t("compare.source"), "b": t("compare.disc"), "split": t("compare.split")}, "b"
        )
        self.view_switch.changed.connect(self.well.set_mode)
        self.zoom_switch = ModeSwitch({"0": t("zoom.fit"), "1": "100%", "2": "200%", "4": "400%"},
                                      "0")  # fmt: skip
        self.zoom_switch.changed.connect(lambda z: self.well.set_zoom(int(z)))
        self.trial_button = QPushButton(t("trial.button"))
        self.trial_button.clicked.connect(self.trial_requested)
        self.trial_result = label("", "muted", wrap=True)
        row.addWidget(self.view_switch)
        row.addWidget(self.zoom_switch)
        row.addStretch()
        row.addWidget(self.trial_button)
        cbox.addWidget(self.compare_row)
        cbox.addWidget(self.trial_result)
        self.side = panel("side")
        self.side.setFixedWidth(300)
        self.side_box = QVBoxLayout(self.side)
        self.side_box.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(center, 1)
        outer.addWidget(self.side)
        self.combos: dict[str, QComboBox] = {}
        self.simple = self._simple_panel()
        self.pro = QWidget()
        pro_box = QVBoxLayout(self.pro)
        pro_box.setContentsMargins(0, 0, 0, 0)
        info, rates = QWidget(), QWidget()
        self.pro_grid, self.rate_grid = QGridLayout(info), QGridLayout(rates)
        for g in (self.pro_grid, self.rate_grid):
            g.setContentsMargins(0, 0, 0, 0)
        self.editor = VideoEditor()
        pro_box.addWidget(info)
        pro_box.addWidget(self.editor)
        pro_box.addWidget(rates)
        self.side_box.addWidget(self.simple)
        self.side_box.addWidget(self.pro)
        self.side_box.addStretch()

    def _simple_panel(self) -> QWidget:
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        box.addWidget(label(t("picture.title.simple"), "pageTitle", wrap=True))
        choices = {
            "content": ("picture.content", ContentProfile.__args__),
            "viewing": ("picture.viewing", ViewingProfile.__args__),
            "audio": ("picture.audio", AudioProfile.__args__),
        }
        for field_name, (key, values) in choices.items():
            box.addWidget(label(t(key), "muted"))
            combo = QComboBox()
            for v in values:
                combo.addItem(t(f"{field_name}.{v}"), v)
            combo.currentIndexChanged.connect(
                lambda _i, f=field_name, c=combo: self.profile_changed.emit(f, c.currentData())
            )
            self.combos[field_name] = combo
            box.addWidget(combo)
        self.quality_card = panel("card")
        q = QVBoxLayout(self.quality_card)
        self.quality_dots = label("", "value")
        self.quality_text = label("", None)
        self.quality_text.setStyleSheet("font-weight: 600;")
        q.addWidget(self.quality_dots)
        q.addWidget(self.quality_text)
        box.addSpacing(6)
        box.addWidget(self.quality_card)
        more = QPushButton(t("picture.all_settings"))
        more.setObjectName("link")
        more.clicked.connect(self.switch_to_pro)
        box.addWidget(more, alignment=Qt.AlignmentFlag.AlignLeft)
        return w

    def set_mode(self, mode: str) -> None:
        self.simple.setVisible(mode == "basit")
        self.pro.setVisible(mode == "pro")
        self.compare_row.setVisible(mode == "pro")
        self.trial_result.setVisible(mode == "pro")
        for b in self.step_buttons:
            b.setVisible(mode == "pro")
        if mode == "basit":
            self.well.set_mode("b")
            self.view_switch.set_mode("b")
            self.well.set_zoom(0)
            self.zoom_switch.set_mode("0")
        self.side.setFixedWidth(300 if mode == "basit" else 290)

    def show_project(self, project: Project, info: SourceInfo, plan: Plan | None,
                     detected=None) -> None:  # fmt: skip
        prof = project.disc.profiles
        for field_name, value in (("content", prof.content), ("viewing", prof.viewing),
                                  ("audio", prof.audio)):  # fmt: skip
            combo = self.combos[field_name]
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(value))
            combo.blockSignals(False)
        if plan:
            dots, text = quality(plan)
            self.quality_dots.setText("●" * dots + "○" * (5 - dots))
            self.quality_text.setText(text)
        self._fill_pro(project, info, plan, detected)

    @staticmethod
    def _origin_text(origin: str) -> str:
        if origin == "override":
            return t("pro.from_override")
        layer, _, value = origin.partition(":")
        return t("pro.from_profile", profile=t(f"{layer}.{value}"))

    def _fill_pro(self, project: Project, info: SourceInfo, plan: Plan | None, detected) -> None:
        for grid in (self.pro_grid, self.rate_grid):
            while grid.count():
                w = grid.takeAt(0).widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        v = info.main_video
        rows = [(label(t("pro.video"), "sectionLabel"), None)]
        if v:
            from dvd.video.pipeline import UnsupportedSource, plan_target

            rows.append((t("pro.source"), f"{v.width}×{v.height} {fps_text(v.fps)}"))
            rows.append(("", f"{(v.color_matrix or '?').upper()} {'HDR' if v.hdr else 'SDR'}"))
            try:
                tg = plan_target(v, project.disc.standard, project.titles[0].video, detected)
                fps = f"{float(tg.fps):g}p"
                rows.append((t("pro.target"), f"{tg.width}×{tg.height} {tg.aspect} {fps}"))
                rows.append((t("pro.active"), f"{tg.active_width}×{tg.active_height}"))
            except UnsupportedSource as exc:
                rows.append((t("pro.target"), str(exc)))
        self.editor.show_title(project.titles[0], v, project.disc.profiles, detected)
        self._fill_grid(self.pro_grid, rows)
        rows = []
        try:
            from dvd.profiles import resolve as resolve_profiles
            from dvd.video.encoders import choose

            wanted = resolve_profiles(project.disc.profiles, project.titles[0].video.overrides)
            name = {"hcenc": "HCEnc", "ffmpeg": "FFmpeg"}[choose(wanted["encoder"])[0]]
        except ValueError:
            name = "?"
        rows.append((t("pro.encoder_used"), f"{name} · 2 pass"))
        if plan:
            rows.append((t("pro.bitrate"), f"{plan.video_kbps / 1000:.2f} Mbps"))
            rows.append((t("pro.peak"), f"{plan.peak_kbps / 1000:.1f} Mbps"))
            viewing = t(f"viewing.{project.disc.profiles.viewing}")
            rows.append(("", t("pro.from_profile", profile=viewing)))
        self._fill_grid(self.rate_grid, rows)

    @staticmethod
    def _fill_grid(grid: QGridLayout, rows: list) -> None:
        # Widgets added to a parent that is already on screen stay hidden until shown.
        for r, (key, value) in enumerate(rows):
            if value is None:
                grid.addWidget(key, r, 0, 1, 2)
                key.show()
                continue
            value_label = label(value, "hint" if not key else "value", True)
            for c, w in enumerate((label(key, "muted"), value_label)):
                grid.addWidget(w, r, c)
                w.show()


class MainWindow(QMainWindow):
    def __init__(self, mode: str = "basit") -> None:
        super().__init__()
        self.mode = mode
        self.project: Project | None = None
        self.project_file: Path | None = None
        self.infos: list[SourceInfo] = []
        self.plan: Plan | None = None
        self.detected = None  # black bars found in the first title, once the preview ran
        self.preview_frame: int | None = None
        self.preview_request = 0
        self.setWindowTitle(t("app.title"))
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        root = panel("root")
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = panel("nav")
        self.nav.setFixedWidth(196)
        self.nav_box = QVBoxLayout(self.nav)
        self.nav_group = QButtonGroup(self)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        vbox.addLayout(body, 1)
        vbox.addWidget(self._budget())

        self.drop = DropZone()
        self.drop.open_requested.connect(self.choose_source)
        self.drop.project_requested.connect(self.choose_project)
        empty = QWidget()
        ebox = QVBoxLayout(empty)
        ebox.setContentsMargins(40, 40, 40, 40)
        ebox.addWidget(self.drop)
        self.pages: dict[str, QWidget] = {"empty": empty}
        self.video_page = VideoPage()
        self.picture_page = PicturePage()
        self.picture_page.profile_changed.connect(self.set_profile)
        self.picture_page.switch_to_pro.connect(lambda: self.set_mode("pro"))
        self.picture_page.position_changed.connect(self._load_preview)
        self.picture_page.frame_step.connect(self.step_frame)
        self.picture_page.trial_requested.connect(self.run_trial)
        self.picture_page.editor.changed.connect(self._video_changed)
        self.pages["video"] = self.video_page
        self.pages["picture"] = self.picture_page
        self.audio_page = TracksPage("both")
        self.subs_page = TracksPage("subs")
        self.build_page = BuildPage()
        for page in (self.audio_page, self.subs_page):
            page.changed.connect(self._tracks_changed)
            page.failed.connect(lambda msg: self.budget_label.setText(msg))
        self.build_page.start_requested.connect(self.start_build)
        self.pages["audio"] = self.audio_page
        self.pages["subs"] = self.subs_page
        self.pages["build"] = self.build_page
        self.building = False
        for key in ("chapters", "menu", "disc"):
            page = QWidget()
            later = QVBoxLayout(page)
            later.setContentsMargins(24, 20, 24, 20)
            later.addWidget(label(t("page.later"), "muted"))
            later.addStretch()
            self.pages[key] = page
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.current = "empty"
        self.set_mode(mode)

    # ---------------------------------------------------------------- layout pieces

    def _topbar(self) -> QWidget:
        bar = panel("topbar")
        box = QHBoxLayout(bar)
        box.setContentsMargins(16, 10, 16, 10)
        box.setSpacing(16)
        self.name_label = label(t("app.title"), "projectName")
        self.summary = label("", "summary")
        self.mode_switch = ModeSwitch({"basit": t("mode.simple"), "pro": t("mode.pro")}, self.mode)
        self.mode_switch.changed.connect(self.set_mode)
        self.build_button = QPushButton()
        self.build_button.setObjectName("primary")
        self.build_button.setEnabled(False)
        self.build_button.clicked.connect(self.start_build)
        box.addWidget(self.name_label)
        box.addWidget(self.summary)
        box.addStretch()
        box.addWidget(self.mode_switch)
        box.addWidget(self.build_button)
        return bar

    def _budget(self) -> QWidget:
        bar = panel("budget")
        box = QHBoxLayout(bar)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(16)
        self.budget_label = label(t("budget.empty"), "muted")
        self.budget_bar = BudgetBar()
        self.budget_numbers = label("", "mono")
        box.addWidget(self.budget_label)
        box.addWidget(self.budget_bar, 1)
        box.addWidget(self.budget_numbers)
        return bar

    # ---------------------------------------------------------------- mode and navigation

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(mode))
        self.mode_switch.set_mode(mode)
        self.build_button.setText(t("build.simple" if mode == "basit" else "build.pro"))
        self.nav.setFixedWidth(196 if mode == "basit" else 168)
        for b in self.nav_group.buttons():
            self.nav_group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        while self.nav_box.count():
            self.nav_box.takeAt(0)
        self.nav_box.setContentsMargins(8, DENSITY[mode].gap, 8, 8)
        self.nav_box.setSpacing(2)
        self.nav_buttons: dict[str, QPushButton] = {}
        for i, (key, text_key) in enumerate(NAV[mode], start=1):
            text = f"{i}   {t(text_key)}" if mode == "basit" else t(text_key)
            b = QPushButton(text)
            b.setCheckable(True)
            b.setEnabled(self.project is not None)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_box.addWidget(b)
            self.nav_buttons[key] = b
        self.nav_box.addStretch()
        self.picture_page.set_mode(mode)
        self.audio_page.show_kind = "both" if mode == "basit" else "audio"
        keys = [k for k, _ in NAV[mode]]
        if self.current not in ("empty", *keys):
            self.current = FALLBACK.get(self.current, "video")
        self.show_page(self.current)
        self._refresh()

    def show_page(self, key: str) -> None:
        self.current = key
        self.stack.setCurrentWidget(self.pages[key])
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)

    # ---------------------------------------------------------------- project

    def choose_source(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(self, t("empty.open"), "", f"Video ({patterns})")
        if path:
            self.open_path(Path(path))

    def choose_project(self) -> None:
        pattern = f"*{proj.PROJECT_SUFFIX}"
        path, _ = QFileDialog.getOpenFileName(self, t("empty.open_project"), "", pattern)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        self.drop.set_busy(t("empty.reading"))
        tasks.run(lambda: self._load(path), self._loaded, self._failed)

    @staticmethod
    def _load(path: Path) -> tuple[Path, Project, list[SourceInfo]]:
        if path.name.endswith(proj.PROJECT_SUFFIX):
            project_file, project = path, proj.load(path)
        else:
            project_file = path.with_name(path.stem + proj.PROJECT_SUFFIX)
            if project_file.exists():
                project = proj.load(project_file)
            else:
                project = proj.new_project(probe(path), project_file.parent)
                proj.save(project, project_file)
        infos = [probe(proj.source_path(project_file, title)) for title in project.titles]
        return project_file, project, infos

    def _loaded(self, result: tuple[Path, Project, list[SourceInfo]]) -> None:
        self.project_file, self.project, self.infos = result
        self.drop.set_busy(None)
        for b in self.nav_buttons.values():
            b.setEnabled(True)
        self.build_button.setEnabled(True)
        self.video_page.show_source(self.infos[0])
        self._refresh()
        self.show_page("picture")
        self._load_preview()

    def _failed(self, message: str) -> None:
        self.drop.set_busy(None)
        self.drop.body.setText(f"{t('error.read')}: {message}")

    def step_frame(self, delta: int) -> None:
        if self.project is not None and self.preview_frame is not None:
            self._load_preview(frame=self.preview_frame + delta)

    def _load_preview(self, position: float = 0.4, frame: int | None = None) -> None:
        from dvd.gui.preview import preview_frames

        p, info, file = self.project, self.infos[0], self.project_file
        self.preview_request += 1
        request = self.preview_request
        page = self.picture_page
        well = page.well
        if well.image is None:
            well.set_image(None, well.aspect, t("picture.preview_loading"))
        source = proj.source_path(file, p.titles[0])

        def shown(frames) -> None:
            if request != self.preview_request:
                return  # a newer frame was asked for while this one rendered
            self.detected, self.preview_seconds = frames.detected, frames.seconds
            self.preview_frame = frames.frame
            well.set_pair(frames.source, frames.disc, frames.aspect,
                          (t("compare.source"), t("compare.disc")))  # fmt: skip
            tc = timecode(frames.seconds)
            page.timecode.setText(t("picture.frame", tc=tc, n=frames.frame)
                                  if self.mode == "pro" else tc)  # fmt: skip
            if not page.slider.isSliderDown():
                page.slider.setValue(round(frames.frame / max(1, frames.frames - 1) * 1000))
            self._refresh()

        tasks.run(
            lambda: preview_frames(
                source, info, p.titles[0], p.disc.standard, p.disc.profiles, position, frame
            ),  # fmt: skip
            shown,
            lambda msg: well.set_image(None, well.aspect, msg),
        )

    def run_trial(self) -> None:
        from dvd.qa.trial import trial_encode

        page, project_file = self.picture_page, self.project_file
        at = getattr(self, "preview_seconds", 0.0)
        page.trial_button.setEnabled(False)
        page.trial_result.setText(t("trial.running", stage="", pct=0))

        def progress(stage: str, f: float) -> None:
            page.trial_result.setText(
                t("trial.running", stage=t(f"trial.{stage}"), pct=round(f * 100))
            )

        def done(r) -> None:
            from PySide6.QtGui import QImage

            page.trial_button.setEnabled(True)
            m = r.measurement
            worst = timecode((r.start + r.worst_frame) / float(m.fps))
            page.trial_result.setText(t("trial.result", ss=m.mean("ssimu2"), xp=m.mean("xpsnr"),
                                        kbps=r.video_kbps / 1000, tc=worst))  # fmt: skip
            labels = (t("compare.before"), t("compare.after"))
            before, after = QImage(str(r.reference_png)), QImage(str(r.encoded_png))
            page.well.set_pair(before, after, page.well.aspect, labels)
            page.well.set_mode("split")
            page.view_switch.set_mode("split")

        def failed(message: str) -> None:
            page.trial_button.setEnabled(True)
            page.trial_result.setText(f"{t('trial.failed')} {message}")

        tasks.run(lambda report: trial_encode(project_file, at, 20, progress=report),
                  done, failed, progress)  # fmt: skip

    def set_profile(self, field_name: str, value: str) -> None:
        if self.project is None:
            return
        setattr(self.project.disc.profiles, field_name, value)
        if field_name == "audio":
            from dvd.profiles import resolve as resolve_profiles
            from dvd.project.edit import apply_audio_profile

            settings = resolve_profiles(self.project.disc.profiles)
            for title, info in zip(self.project.titles, self.infos, strict=True):
                apply_audio_profile(title, info, settings)
        proj.save(self.project, self.project_file)
        self._refresh()

    def _video_changed(self) -> None:
        """Crop or pre-processing edited: the plan, the panel and the preview all change."""
        proj.save(self.project, self.project_file)
        self._refresh()
        self._load_preview(frame=self.preview_frame)

    def _refresh(self) -> None:
        p = self.project
        if p is None:
            self.summary.setText("")
            self.budget_bar.set_plan(None, self.mode)
            return
        self.name_label.setText(p.disc.name)
        prof = p.disc.profiles
        if self.mode == "basit":
            parts = [p.disc.media.upper(), t(f"viewing.{prof.viewing}"), t(f"audio.{prof.audio}")]
        else:
            parts = [p.disc.standard.upper(), p.disc.media.upper(), t(f"content.{prof.content}"),
                     t(f"viewing.{prof.viewing}"), prof.audio]  # fmt: skip
        self.summary.setText("  ·  ".join(parts))
        self.plan = estimate(p, self.infos)
        self.budget_bar.set_plan(self.plan, self.mode)
        used = self.plan.estimated_bytes / 1e9
        numbers = f"{used:.2f} / {self.plan.capacity_bytes / 1e9:.2f} GB"
        if self.mode == "pro":
            numbers += f"  ·  video {self.plan.video_kbps / 1000:.1f} Mbps"
            self.budget_label.setText(t("budget.disc"))
            self.budget_label.setObjectName("muted")
        else:
            state = (
                ("budget.fits", "ok")
                if self.plan.fits and not self.plan.warnings
                else (("budget.tight", "warn") if self.plan.fits else ("budget.too_big", "error"))
            )
            self.budget_label.setText(t(state[0]))
            self.budget_label.setObjectName(state[1])
        self.budget_label.style().unpolish(self.budget_label)
        self.budget_label.style().polish(self.budget_label)
        self.budget_numbers.setText(numbers)
        self.picture_page.show_project(p, self.infos[0], self.plan, self.detected)
        for page in (self.audio_page, self.subs_page):
            page.show_project(p, self.infos[0], self.project_file.parent, self.mode)
        self.build_page.set_summary(t("build.summary", folder=self._output_folder()))

    def _output_folder(self) -> Path:
        from dvd.build import safe_name

        return self.project_file.parent / safe_name(self.project.disc.name)

    def _tracks_changed(self) -> None:
        proj.save(self.project, self.project_file)
        self._refresh()

    # ---------------------------------------------------------------- build

    def start_build(self) -> None:
        if self.project is None or self.building:
            self.show_page("build")
            return
        from dvd.build import build

        self.building = True
        self.build_button.setEnabled(False)
        self.show_page("build")
        self.build_page.running()
        project_file = self.project_file
        tasks.run(
            lambda progress: build(project_file, progress=progress),
            self._built,
            self._build_failed,
            self.build_page.progress,
        )

    def _built(self, result) -> None:
        self.building = False
        self.build_button.setEnabled(True)
        lines = [t("build.wrote", path=result.video_ts)]
        if result.iso:
            lines.append(t("build.wrote", path=result.iso))
        self.build_page.finished(result.video_ts.parent, lines, result.warnings)

    def _build_failed(self, message: str) -> None:
        self.building = False
        self.build_button.setEnabled(True)
        self.build_page.failed(message)

    # ---------------------------------------------------------------- drag and drop

    def _dropped_path(self, event) -> Path | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() in VIDEO_SUFFIXES or path.name.endswith(proj.PROJECT_SUFFIX):
            return path
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._dropped_path(event):
            event.acceptProposedAction()
            self.drop.set_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.set_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop.set_active(False)
        path = self._dropped_path(event)
        if path:
            self.show_page("empty")
            self.open_path(path)
