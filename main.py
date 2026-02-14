# -*- coding: utf-8 -*-
"""
Unblock for Windows
- Multi-file/folder selection with removal
- Pause/Resume / Cancel
- Drag & Drop
- Progress and status logging
- Windows 11 Mica blur
- Modern theme-aware UI
- Tray icon with click-to-restore
- Embedded SVG for title bar icon
"""
import sys
import subprocess
import winreg
import os
import ctypes
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QLabel, QTextEdit, QListWidget, QListWidgetItem,
    QProgressBar, QSystemTrayIcon, QMenu, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont, QAction
from PyQt6.QtSvg import QSvgRenderer

# ----------------------------
# Global Variables
# ----------------------------
APP_NAME = "Unblock for Windows"


# ----------------------------
# Detect Windows Theme
# ----------------------------
def is_dark_mode():
    try:
        registry = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(registry, "AppsUseLightTheme")
        return value == 0  # Dark mode
    except _:
        return False

# ----------------------------
# Windows 11 Mica Blur
# ----------------------------
def apply_mica(window_id):
    try:
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(window_id),
            ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(ctypes.c_int(DWMSBT_MAINWINDOW)),
            ctypes.sizeof(ctypes.c_int)
        )
    except Exception as e:
        print("Mica not supported:", e)

# ----------------------------
# Worker Thread with Pause/Cancel
# ----------------------------
class UnblockWorker(QThread):
    progress_signal = pyqtSignal(int)
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self._pause = False
        self._cancel = False

    def pause(self):
        self._pause = True

    def resume(self):
        self._pause = False

    def cancel(self):
        self._cancel = True

    def run(self):
        files_to_unblock = []

        for path in self.paths:
            if self._cancel:
                self.output_signal.emit("❌ Operation cancelled.")
                self.finished_signal.emit()
                return
            if os.path.isfile(path):
                files_to_unblock.append(path)
            elif os.path.isdir(path):
                for root, _, filenames in os.walk(path):
                    for f in filenames:
                        files_to_unblock.append(os.path.join(root, f))

        total = len(files_to_unblock)
        if total == 0:
            self.output_signal.emit("No files to unblock.")
            self.finished_signal.emit()
            return

        for i, file in enumerate(files_to_unblock):
            while self._pause:
                self.msleep(200)
            if self._cancel:
                self.output_signal.emit("❌ Operation cancelled.")
                self.finished_signal.emit()
                return

            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"Unblock-File -LiteralPath '{file}'"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.output_signal.emit(f"✅ Processed: {file}")
            except Exception as e:
                self.error_signal.emit(f"❌ Error: {file} -> {e}")

            percent = int((i + 1) / total * 100)
            self.progress_signal.emit(percent)

        self.output_signal.emit("🎉 Completed all files!")
        self.finished_signal.emit()

# ----------------------------
# Main App
# ----------------------------
class UnblockApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        # Set window icon from embedded SVG
        self.setWindowIcon(self.get_embedded_icon())

        # Allow .ICO for the EXE itself if bundled with PyInstaller
        # Example: pyinstaller --onefile --icon=resources/favicon.ico main.py

        self.setAcceptDrops(True)
        self.resize(850, 600)

        # Apply Mica
        try:
            hwnd = int(self.winId())
            apply_mica(hwnd)
        except _:
            pass

        self.selected_paths = []

        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Title
        title = QLabel("Unblock Downloaded Files")
        title.setFont(QFont("Segoe UI", 20))
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "Drag & drop files/folders here OR use the buttons below.\n"
            "Right-click any item to remove it.\n"
            "Use Pause/Resume/Cancel buttons for long sessions."
        )
        instructions.setStyleSheet("color: gray;")
        layout.addWidget(instructions)

        # Selected files/folders list
        self.list_widget = QListWidget()
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.list_widget)

        # Buttons row
        btn_row = QHBoxLayout()
        self.file_button = QPushButton("Select Files")
        self.file_button.clicked.connect(self.select_files)
        btn_row.addWidget(self.file_button)

        self.folder_button = QPushButton("Select Folders")
        self.folder_button.clicked.connect(self.select_folders)
        btn_row.addWidget(self.folder_button)

        self.unblock_button = QPushButton("Start Unblock")
        self.unblock_button.setEnabled(False)
        self.unblock_button.clicked.connect(self.start_unblock)
        btn_row.addWidget(self.unblock_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.pause_resume)
        btn_row.addWidget(self.pause_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        btn_row.addWidget(self.cancel_button)

        layout.addLayout(btn_row)

        # Progress bar
        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        # Status log
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        self.setLayout(layout)

        self.worker = None
        self.paused = False

        self.setup_tray()
        self.apply_theme()
        self.fade_in()

    # ----------------------------
    # Embedded SVG Icon
    # ----------------------------
    def get_embedded_icon(self):
        svg_data = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
   svg:contrastcolor="ffffff"
   svg:template="InvertedHex1"
   svg:presentation="2.5"
   svg:layouttype="undefined"
   svg:specialfontid="undefined"
   svg:id1="341"
   svg:id2="666"
   svg:companyname=APP_NAME
   svg:companytagline=""
   version="1.1"
   viewBox="65 148.61381 91.102356 119.78344"
   class="watermark-logo"
   style="opacity:1"
   id="svg3"
   sodipodi:docname="logo-small.svg"
   width="91.102356"
   height="119.78344"
   xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
   xmlns="http://www.w3.org/2000/svg"
   xmlns:svg="http://www.w3.org/2000/svg">
  <defs
     id="defs3" />
  <sodipodi:namedview
     id="namedview3"
     pagecolor="#ffffff"
     bordercolor="#000000"
     borderopacity="0.25"
     inkscape:showpageshadow="2"
     inkscape:pageopacity="0.0"
     inkscape:pagecheckerboard="0"
     inkscape:deskcolor="#d1d1d1"
     inkscape:export-bgcolor="#000000a3">
    <inkscape:page
       x="0"
       y="0"
       width="91.102356"
       height="119.78344"
       id="page2"
       margin="0"
       bleed="0" />
  </sodipodi:namedview>
  <g
     fill="#101820"
     fill-rule="none"
     stroke="none"
     stroke-width="1"
     stroke-linecap="butt"
     stroke-linejoin="miter"
     stroke-miterlimit="10"
     stroke-dasharray="none"
     stroke-dashoffset="0"
     font-family="none"
     font-weight="none"
     font-size="none"
     text-anchor="none"
     style="mix-blend-mode:normal"
     id="g3"
     transform="translate(-164.44885)">
    <g
       data-paper-data="{&quot;isGlobalGroup&quot;:true,&quot;bounds&quot;:{&quot;x&quot;:65,&quot;y&quot;:148.6138128945858,&quot;width&quot;:420,&quot;height&quot;:172.7723742108284}}"
       id="g2">
      <g
         data-paper-data="{&quot;isIcon&quot;:&quot;true&quot;,&quot;selectedEffects&quot;:{&quot;container&quot;:&quot;&quot;,&quot;transformation&quot;:&quot;&quot;,&quot;pattern&quot;:&quot;&quot;},&quot;fillRule&quot;:&quot;evenodd&quot;,&quot;fillRuleOriginal&quot;:&quot;evenodd&quot;,&quot;iconType&quot;:&quot;icon&quot;,&quot;rawIconId&quot;:&quot;doaHHeTSl_6y97mFBk7cbrj7LoHLEuZN2NRxe3auol&quot;,&quot;source&quot;:&quot;ai&quot;,&quot;iconStyle&quot;:&quot;standalone&quot;,&quot;bounds&quot;:{&quot;x&quot;:229.44886237468904,&quot;y&quot;:148.6138128945858,&quot;width&quot;:91.10227525062191,&quot;height&quot;:119.78343217907019},&quot;suitableAsStandaloneIcon&quot;:true}"
         fill-rule="evenodd"
         id="g1">
        <path
           d="m 263.62452,157.41647 c 1.21515,-4.32516 4.73355,-7.69971 8.97043,-8.60368 1.18263,-0.25232 3.43699,-0.26709 4.67343,-0.0305 3.78183,0.72352 7.09202,3.43936 8.66465,7.10829 0.86141,2.00995 0.87475,2.16088 0.93487,10.52113 l 0.0543,7.55801 -0.26881,-0.0854 c -0.21079,-0.0669 -4.01719,-1.82319 -5.60175,-2.58479 -0.24682,-0.11852 -0.3287,-0.0998 -0.47492,0.10818 -0.55985,0.79754 -1.61099,2.07726 -1.80517,2.19774 -0.24659,0.15277 -0.58418,-0.16494 -1.44161,-1.35809 -0.37292,-0.51858 -0.42275,-0.68819 -0.42275,-1.43733 0,-0.70665 0.0957,-1.0788 0.56991,-2.2155 0.72198,-1.73085 0.78748,-1.83042 1.98391,-3.01127 1.45495,-1.43593 2.08615,-2.93771 2.08335,-4.95655 -0.003,-1.90622 -0.57014,-3.3978 -1.79886,-4.72789 -1.29305,-1.39987 -2.81679,-2.07738 -4.66477,-2.07424 -2.78661,0.005 -5.12613,1.67309 -6.15808,4.39191 -0.94283,2.48457 -0.25688,5.48002 1.69615,7.40414 0.69273,0.68263 0.76034,0.79721 0.69367,1.17615 -0.1137,0.64461 -1.2596,5.88645 -1.32721,6.0701 -0.0601,0.16307 0.12072,0.22553 0.99102,0.34087 0.25945,0.0344 1.46477,0.48381 2.67875,0.99851 1.21374,0.51493 3.07905,1.2252 4.14516,1.57894 1.62175,0.53809 1.97619,0.61647 2.16944,0.48007 0.12727,-0.0898 0.63448,-0.64969 1.12741,-1.24463 0.52031,-0.6277 0.96692,-1.05396 1.06519,-1.01629 0.17804,0.0681 6.44351,3.83751 7.84465,4.71928 0.44919,0.28262 0.81649,0.57599 0.81649,0.65202 0,0.076 -0.16704,0.40193 -0.37175,0.72432 -0.20424,0.32215 -0.87334,1.40699 -1.48653,2.41017 -0.61342,1.00342 -1.74809,2.85328 -2.52154,4.111 -0.77391,1.25749 -2.21108,3.60964 -3.19415,5.22672 -0.9833,1.61708 -2.52832,4.1454 -3.43348,5.61883 -0.9054,1.4732 -1.6655,2.76087 -1.68937,2.86147 -0.0468,0.19699 0.56546,0.34578 7.59666,1.84635 2.04615,0.43679 3.74581,0.81953 3.77716,0.85088 0.0608,0.0606 -0.68875,1.17935 -6.78017,10.12147 -5.02272,7.3737 -5.77885,8.50603 -5.71943,8.56569 0.0568,0.0566 6.71419,3.24866 8.23652,3.94911 0.55704,0.25617 1.01278,0.51773 1.01278,0.58114 0,0.11393 -0.54464,1.04343 -6.33799,10.81677 -6.89293,11.62812 -7.67527,12.89965 -9.84143,15.98992 -0.53575,0.76409 -0.53809,0.76573 -0.68735,0.43866 -0.2143,-0.47048 0.1282,-1.99772 3.03319,-13.53576 1.36394,-5.41599 2.46188,-9.96589 2.43989,-10.1107 -0.0318,-0.21126 -0.48148,-0.43187 -2.26138,-1.1094 -4.70641,-1.79184 -5.61298,-2.14253 -5.65953,-2.18886 -0.0264,-0.0264 1.05278,-2.6839 2.39801,-5.90565 3.74581,-8.97066 3.8932,-9.34311 3.73107,-9.44347 -0.0798,-0.0491 -1.18824,-0.28378 -2.46328,-0.52124 -4.39923,-0.81953 -8.01519,-1.54596 -8.09568,-1.62667 -0.0683,-0.0681 0.89674,-3.64193 3.0381,-11.2531 0.24284,-0.86234 0.64547,-2.3325 0.8951,-3.26667 0.2494,-0.93441 1.0205,-3.7568 1.71323,-6.27226 2.10978,-7.65935 2.95692,-11.13612 2.91317,-11.95612 l -0.0381,-0.7187 -1.01909,-0.51306 -1.01909,-0.51282 -0.61436,0.20424 c -0.33783,0.1123 -1.63088,0.58629 -2.87317,1.05348 l -2.25928,0.84901 0.0444,-9.09933 c 0.0437,-8.96785 0.0489,-9.11447 0.33806,-10.14465 z m -30.53219,18.09575 c 8.13809,-2.19026 17.60915,-5.34201 24.47564,-8.14488 0.79052,-0.32276 1.48232,-0.59155 1.5373,-0.59742 0.055,-0.006 0.0845,1.82284 0.0653,4.06356 l -0.0344,4.07421 -2.28688,0.89066 c -5.17156,2.01386 -11.61015,4.18142 -17.3642,5.84576 -1.24959,0.36146 -2.29755,0.6829 -2.32893,0.71402 -0.0312,0.0314 -0.0902,1.81196 -0.13078,3.9566 -0.10834,5.71826 0.2919,12.10328 0.82346,13.13781 0.67322,1.31013 2.80443,3.38435 3.74929,3.64895 0.30304,0.0847 1.60933,0.43047 2.90297,0.76806 l 2.35204,0.61412 0.21561,0.57482 c 0.11866,0.31631 0.70366,2.16733 1.30003,4.11335 l 1.0843,3.53806 1.1175,0.65623 c 3.66687,2.15283 4.78119,2.81328 4.82985,2.86194 0.03,0.0297 -0.15979,0.48077 -0.42158,1.00202 -0.26179,0.52124 -0.7056,1.66597 -0.98634,2.54376 l -0.51048,1.59602 1.46244,2.25857 c 0.80409,1.24229 1.5132,2.34701 1.57567,2.45486 0.0627,0.10785 -0.55751,-0.50955 -1.37798,-1.37213 -0.8207,-0.86234 -1.86039,-1.95514 -2.31028,-2.42819 l -0.81829,-0.86048 0.65387,-2.38046 c 0.35954,-1.3092 0.65315,-2.42164 0.65221,-2.4717 -0.002,-0.12072 -1.69405,-1.21889 -3.26092,-2.11656 -0.94278,-0.54019 -1.51054,-0.98658 -2.28618,-1.79769 l -1.03203,-1.07922 -0.66473,-2.31823 -0.66456,-2.31846 -2.26437,-0.0948 -2.26437,-0.0945 -1.30487,-0.95078 c -0.71765,-0.52288 -1.41373,-1.02869 -1.54687,-1.12414 -0.20373,-0.14622 -0.47562,-0.13055 -1.72053,0.0987 -0.81329,0.14996 -2.36067,0.40801 -3.4387,0.57365 l -1.96005,0.30133 -0.0855,-0.29759 c -0.14334,-0.49878 -0.75083,-5.08261 -0.95846,-7.23216 -0.37018,-3.83143 -0.51993,-9.85523 -0.34719,-13.96787 0.17236,-4.10282 0.46845,-7.57139 0.66276,-7.76581 0.0686,-0.0685 1.37778,-0.46182 2.90922,-0.87405 z m 57.73099,-0.54534 v -8.07034 l 0.35935,0.13995 c 8.15159,3.17515 19.69525,6.93656 27.06077,8.81777 0.88434,0.22576 1.52584,0.45972 1.59041,0.57927 0.16985,0.31513 0.51773,4.69869 0.66349,8.35817 0.13429,3.36961 0.009,8.86725 -0.28168,12.34822 -0.26039,3.11975 -0.79029,7.44108 -0.92926,7.58028 -0.0337,0.0337 -0.29221,-0.025 -0.57459,-0.13031 -0.28214,-0.10528 -1.7626,-0.63869 -3.29007,-1.1852 l -2.77701,-0.99383 -1.5759,1.28463 c -1.50876,1.22965 -2.02439,1.69592 -2.62868,1.90367 -0.45457,0.15628 -0.95944,0.16658 -1.97432,0.24518 -1.13513,0.0882 -2.143,0.22389 -2.23985,0.30133 -0.0969,0.0777 -0.63261,1.11151 -1.19058,2.29718 -0.58699,1.24743 -1.15128,2.2663 -1.33868,2.41743 -0.17827,0.14388 -0.88223,0.64711 -1.56467,1.11853 l -1.24088,0.8572 0.0192,3.25872 0.0192,3.25919 -2.82263,1.34991 c -1.55251,0.7428 -2.8472,1.32581 -2.87738,1.29586 -0.0299,-0.0302 0.88294,-0.7552 2.02883,-1.6117 l 2.08311,-1.55672 0.0405,-3.31791 0.0402,-3.31767 1.30311,-0.82024 c 0.71683,-0.45106 1.32745,-0.89861 1.35692,-0.9943 0.0887,-0.28753 1.95537,-5.05453 2.45533,-6.27015 l 0.46486,-1.13069 1.39131,-0.34625 c 0.76525,-0.19067 2.12124,-0.56008 3.01307,-0.82094 l 1.62175,-0.47422 1.4367,-1.18497 c 0.79029,-0.65132 1.57309,-1.30218 1.7399,-1.44582 0.28051,-0.24191 0.31817,-0.441 0.50393,-2.67875 0.24822,-2.98523 0.3776,-9.50594 0.23699,-11.93717 l -0.10481,-1.81056 -2.4827,-0.70607 c -1.36558,-0.38836 -2.8355,-0.81977 -3.26667,-0.95873 -0.43141,-0.13873 -2.019,-0.64571 -3.52823,-1.12671 -2.93002,-0.93323 -6.65242,-2.23729 -9.73475,-3.41032 -1.04225,-0.39632 -2.14464,-0.80901 -2.45018,-0.91686 z m 20.44227,31.90802 c 0.25384,-1.25305 0.39608,-1.68703 0.61085,-1.86413 0.22717,-0.18693 0.43047,-0.21594 1.07969,-0.15347 0.43983,0.0423 1.99117,0.18108 3.44752,0.30835 1.45612,0.12727 2.68881,0.27256 2.73911,0.32285 0.12727,0.12727 -0.25431,2.28969 -0.93628,5.3065 -2.11282,9.34826 -5.75826,18.20358 -10.83783,26.32593 -6.4662,10.33998 -15.56436,19.90768 -26.54139,27.91142 -2.0906,1.5242 -4.71086,3.25731 -4.92516,3.25731 -0.20097,0 -0.22904,-0.0791 -0.1757,-0.49013 0.16026,-1.23222 0.72081,-7.34961 0.72268,-7.88769 2.3e-4,-0.11604 0.2494,-0.38064 0.55353,-0.58792 0.30414,-0.20751 1.31832,-0.98938 2.25413,-1.73733 9.60397,-7.67807 17.19127,-16.3694 22.76775,-26.08074 4.42473,-7.70545 7.43944,-15.74077 9.24111,-24.63094 z m -79.66485,0.6422 c 0.26774,-0.006 1.63337,-0.0856 3.03481,-0.17663 3.09607,-0.20143 3.51422,-0.23466 3.80196,-0.0566 0.0542,0.0335 0.10376,0.0744 0.16583,0.12329 0.18934,0.14879 0.34431,0.36169 0.34431,0.47305 0,0.26226 0.94893,4.03731 1.4388,5.7241 2.77593,9.55928 7.56145,19.02896 13.829,27.3649 5.11981,6.81011 11.89319,13.70585 18.26136,18.59193 l 0.79637,0.61108 0.22132,1.86998 c 0.12189,1.02845 0.30601,2.6343 0.40941,3.5687 0.10318,0.93417 0.21757,1.94859 0.25361,2.25389 0.0901,0.75988 -0.0805,0.73227 -1.54081,-0.2501 -5.09431,-3.4267 -11.2063,-8.49527 -16.0449,-13.30602 -12.9645,-12.89006 -21.05686,-27.18827 -24.84915,-43.90579 -0.49916,-2.20079 -0.64054,-2.72577 -0.47786,-2.84883 0.0676,-0.0512 0.18751,-0.0332 0.35594,-0.037 z"
           data-paper-data="{&quot;isPathIcon&quot;:true}"
           style="fill:#ffffff"
           id="path1" />
      </g>
      <g
         inkscape:groupmode="layer"
         id="layer1"
         inkscape:label="Layer 1" />
      <g
         inkscape:groupmode="layer"
         id="layer2"
         inkscape:label="Layer 2" />
    </g>
  </g>
</svg>
"""  # Keep your full SVG here

        renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)

    # ----------------------------
    # Handle close button
    # ----------------------------
    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                "Application minimized to tray. Click the tray icon to restore.",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )
            event.ignore()
        else:
            if self.worker and self.worker.isRunning():
                self.worker.cancel()
            event.accept()

    # ----------------------------
    # Drag & Drop
    # ----------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path not in self.selected_paths:
                self.selected_paths.append(path)
        self.update_list()
        self.unblock_button.setEnabled(bool(self.selected_paths))

    # ----------------------------
    # File/Folder Selection
    # ----------------------------
    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", "All Files (*)")
        for f in files:
            if f not in self.selected_paths:
                self.selected_paths.append(f)
        self.update_list()
        self.unblock_button.setEnabled(bool(self.selected_paths))

    def select_folders(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder and folder not in self.selected_paths:
            self.selected_paths.append(folder)
        self.update_list()
        self.unblock_button.setEnabled(bool(self.selected_paths))

    # ----------------------------
    # Update List
    # ----------------------------
    def update_list(self):
        self.list_widget.clear()
        for path in self.selected_paths:
            item = QListWidgetItem(path)
            self.list_widget.addItem(item)

    # ----------------------------
    # Context menu to remove items
    # ----------------------------
    def show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if item:
            menu = QMenu()
            remove_action = QAction("Remove", self)
            remove_action.triggered.connect(lambda: self.remove_item(item))
            menu.addAction(remove_action)
            menu.exec(self.list_widget.mapToGlobal(pos))

    def remove_item(self, item):
        path = item.text()
        if path in self.selected_paths:
            self.selected_paths.remove(path)
        self.update_list()
        self.unblock_button.setEnabled(bool(self.selected_paths))

    # ----------------------------
    # Pause / Resume / Cancel
    # ----------------------------
    def pause_resume(self):
        if self.worker and self.worker.isRunning():
            if not self.paused:
                self.worker.pause()
                self.paused = True
                self.pause_button.setText("Resume")
                self.output.append("⏸ Paused...")
            else:
                self.worker.resume()
                self.paused = False
                self.pause_button.setText("Pause")
                self.output.append("▶ Resumed...")

    def cancel(self):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "Cancel",
                "Are you sure you want to cancel?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.unblock_button.setEnabled(True)
                self.pause_button.setEnabled(False)
                self.cancel_button.setEnabled(False)

    # ----------------------------
    # Start Unblock
    # ----------------------------
    def start_unblock(self):
        if not self.selected_paths:
            return
        self.progress.setValue(0)
        self.output.clear()
        self.unblock_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.worker = UnblockWorker(self.selected_paths)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.output_signal.connect(self.output.append)
        self.worker.error_signal.connect(self.output.append)
        self.worker.finished_signal.connect(self.finish_unblock)
        self.worker.start()

    def finish_unblock(self):
        self.unblock_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.paused = False
        self.pause_button.setText("Pause")
        self.tray.showMessage("Unblock for Windows", "✅ Finished successfully")

    # ----------------------------
    # Fade Animation
    # ----------------------------
    def fade_in(self):
        self.setWindowOpacity(0)
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)
        self.anim.start()

    # ----------------------------
    # System Tray with click-to-restore
    # ----------------------------
    def setup_tray(self):
        self.tray = QSystemTrayIcon(QIcon(self.get_embedded_icon()), self)
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.exit_app)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    def exit_app(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        QApplication.quit()

    # ----------------------------
    # Theme Styling
    # ----------------------------
    def apply_theme(self):
        dark = is_dark_mode()
        if dark:
            self.setStyleSheet("""
                QWidget { background-color: #1e1e1e; color: white; font-family: Segoe UI; }
                QPushButton { background-color: #2d2d2d; border-radius: 10px; padding: 8px; }
                QPushButton:hover { background-color: #3a3a3a; }
                QProgressBar { border-radius: 6px; text-align: center; }
                QProgressBar::chunk { background-color: #0078d7; border-radius: 6px; }
                QListWidget { background-color: #252526; border: 1px solid #3a3a3a; border-radius: 6px; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #f3f3f3; font-family: Segoe UI; }
                QPushButton { border-radius: 10px; padding: 8px; }
                QProgressBar::chunk { background-color: #0078d7; }
                QListWidget { background-color: #ffffff; border: 1px solid #d0d0d0; border-radius: 6px; }
            """)

# ----------------------------
# Run App
# ----------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = UnblockApp()
    window.show()
    sys.exit(app.exec())
