"""
Modern Dark & Crimson-Flame Aesthetic Theme for Hongguo Downloader (PyQt6)
Features sleek glassmorphic tones, vibrant glowing accents, and high-DPI typography.
"""

MAIN_STYLESHEET = """
/* Global Application Reset & Typography */
* {
    font-family: 'Segoe UI', 'SF Pro Display', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
    outline: none;
}

QMainWindow, QDialog {
    background-color: #120E0D;
    color: #EDE5DF;
}

QWidget#CentralWidget {
    background: #120E0D;
}

/* Sidebar / Top Navigation Bar */
QFrame#NavHeader {
    background-color: #16110F;
    border-bottom: 1px solid #241A16;
    padding: 8px 18px;
}

QLabel#AppTitle {
    font-size: 17px;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: 0.3px;
}

QLabel#AppSubtitle {
    font-size: 10.5px;
    color: #84746D;
    font-weight: 700;
    letter-spacing: 1px;
}

/* Modern Segmented Capsule Nav Frame */
QFrame#NavCapsule {
    background-color: #1A1311;
    border: 1px solid #2C1F1B;
    border-radius: 18px;
    padding: 2px 3px;
}

/* Navigation Buttons (Tab Chips) */
QPushButton[class="NavBtn"], QPushButton.NavBtn {
    background-color: transparent;
    color: #9E8E87;
    font-size: 12px;
    font-weight: 700;
    padding: 6px 14px;
    border-radius: 15px;
    border: none;
}

QPushButton[class="NavBtn"]:hover, QPushButton.NavBtn:hover {
    color: #FFFFFF;
    background-color: #261B18;
}

QPushButton[class="NavBtn"]:checked, QPushButton.NavBtn:checked, QPushButton.NavBtn.active {
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF451D, stop:1 #FF7830);
    font-weight: 800;
    border: none;
}

/* Filter Chips (Categories & Genres) */
QPushButton[class="FilterChip"], QPushButton.FilterChip {
    background-color: #1A1310;
    color: #A89891;
    font-size: 11.5px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 14px;
    border: 1px solid #2B1E19;
}

QPushButton[class="FilterChip"]:hover, QPushButton.FilterChip:hover {
    color: #FFFFFF;
    border-color: #FF5A22;
    background-color: #261B16;
}

QPushButton[class="FilterChip"]:checked, QPushButton.FilterChip:checked {
    color: #FFFFFF;
    background-color: #FF5A22;
    border: 1px solid #FF5A22;
    font-weight: 800;
}

/* Search Bar & Inputs */
QLineEdit {
    background-color: #1A1412;
    color: #F0EAE6;
    border: 1px solid #30221D;
    border-radius: 11px;
    padding: 8px 14px;
    font-size: 12.5px;
    selection-background-color: #FF5A22;
}

QLineEdit:focus {
    border: 1.5px solid #FF5A22;
    background-color: #201815;
}

QComboBox {
    background-color: #1C1726;
    color: #F5F3F7;
    border: 1px solid #362B4A;
    border-radius: 10px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 600;
}

QComboBox:hover {
    border-color: #FF6E38;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left-width: 0px;
}

QComboBox QAbstractItemView {
    background-color: #1E1729;
    color: #F5F3F7;
    border: 1px solid #3B2E52;
    selection-background-color: #FF4D26;
    selection-color: #FFFFFF;
    padding: 6px;
    border-radius: 8px;
}

/* Radio Buttons */
QRadioButton {
    color: #E2DDF0;
    font-size: 13px;
    font-weight: 600;
    spacing: 8px;
}

QRadioButton:hover {
    color: #FFFFFF;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #4D3C66;
    background-color: #1F172B;
}

QRadioButton::indicator:hover {
    border-color: #FF7043;
}

QRadioButton::indicator:checked {
    border: 3px solid #1F172B;
    background-color: #FF552B;
}

/* Primary Action Buttons */
QPushButton.PrimaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF7830);
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 700;
    padding: 9px 18px;
    border-radius: 10px;
    border: none;
}

QPushButton.PrimaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5236, stop:1 #FF8B47);
}

QPushButton.PrimaryBtn:pressed {
    background: #E63518;
}

QPushButton.SecondaryBtn {
    background-color: #241C19;
    color: #D4C8C2;
    font-size: 12px;
    font-weight: 600;
    padding: 8px 14px;
    border-radius: 9px;
    border: 1px solid #382721;
}

QPushButton.SecondaryBtn:hover {
    background-color: #332520;
    color: #FFFFFF;
    border-color: #FF5A22;
}

/* Modern Harvester Drama Card */
QFrame.DramaCard {
    background-color: #191311;
    border: 1px solid #2C1F1A;
    border-radius: 12px;
}

QFrame.DramaCard:hover {
    border: 1.5px solid #FF5A22;
    background-color: #221815;
}

QFrame.DramaCardSelected {
    border: 2px solid #FF5A22;
    background-color: #251B17;
    border-radius: 12px;
}

QLabel.CardTitle {
    color: #FFFFFF;
    font-size: 11.5px;
    font-weight: 600;
    line-height: 1.25;
}

QPushButton.CardPlayBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF7830);
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 800;
    border-radius: 7px;
    border: none;
    padding: 4px 0px;
}

QPushButton.CardPlayBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5236, stop:1 #FF8B47);
}

QPushButton.CardPlayBtn:pressed {
    background: #E63518;
}

QPushButton.CardDlBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284C7, stop:1 #06B6D4);
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 800;
    border-radius: 7px;
    border: none;
    padding: 4px 0px;
}

QPushButton.CardDlBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369A1, stop:1 #0891B2);
}

QPushButton.CardDlBtn:pressed {
    background: #075985;
}

QPushButton.CardFavFloatingBtn {
    background-color: rgba(18, 14, 26, 0.72);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 12px;
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 700;
}

QPushButton.CardFavFloatingBtn:hover {
    background-color: rgba(225, 29, 72, 0.9);
    border-color: #FB7185;
    color: #FFFFFF;
}

QPushButton.CardFavFloatingBtn.saved {
    background-color: #E11D48;
    border-color: #FB7185;
    color: #FFFFFF;
}

/* Badges Matching Reference Screenshot */
QLabel.BadgeRankGold {
    background-color: #EF4444;
    color: #FFFFFF;
    font-size: 10.5px;
    font-weight: 900;
    border-radius: 10px;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    qproperty-alignment: AlignCenter;
}

QLabel.BadgeRankSilver {
    background-color: #F59E0B;
    color: #FFFFFF;
    font-size: 10.5px;
    font-weight: 900;
    border-radius: 10px;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    qproperty-alignment: AlignCenter;
}

QLabel.BadgeRankBronze {
    background-color: #3B82F6;
    color: #FFFFFF;
    font-size: 10.5px;
    font-weight: 900;
    border-radius: 10px;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    qproperty-alignment: AlignCenter;
}

QLabel.BadgeScore {
    background-color: rgba(0, 0, 0, 0.7);
    color: #FFC107;
    border: 1px solid rgba(0, 0, 0, 0.5);
    font-size: 10.5px;
    font-weight: 800;
    border-radius: 6px;
    padding: 2px 6px;
}

/* Sticky Bottom Harvester Bar */
QFrame#BottomHarvesterBar {
    background-color: #16110F;
    border-top: 1px solid #2C1F1A;
}

QLabel.BadgeHeat {
    background-color: rgba(255, 77, 34, 0.22);
    color: #FF7043;
    border: 1px solid rgba(255, 112, 67, 0.4);
    font-size: 11px;
    font-weight: 700;
    border-radius: 6px;
    padding: 2px 6px;
}

QLabel.BadgeStatusCompleted {
    background-color: rgba(34, 197, 94, 0.18);
    color: #4ADE80;
    border: 1px solid rgba(74, 222, 128, 0.4);
    font-size: 10px;
    font-weight: 700;
    border-radius: 6px;
    padding: 2px 5px;
}

QLabel.BadgeStatusOngoing {
    background-color: rgba(59, 130, 246, 0.18);
    color: #60A5FA;
    border: 1px solid rgba(96, 165, 250, 0.4);
    font-size: 10px;
    font-weight: 700;
    border-radius: 6px;
    padding: 2px 5px;
}

/* Heart / Bookmark Button */
QPushButton.FavBtn {
    background-color: #241D30;
    border: 1px solid #362A48;
    color: #A39BB0;
    border-radius: 8px;
    font-size: 13px;
    padding: 4px 8px;
}

QPushButton.FavBtn:hover {
    border-color: #FF4571;
    color: #FF4571;
}

QPushButton.FavBtn.saved {
    background-color: rgba(255, 69, 113, 0.22);
    border-color: #FF4571;
    color: #FF4571;
    font-weight: 700;
}

/* Scroll Area & Scrollbar */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    border: none;
    background-color: transparent;
    width: 6px;
    margin: 0px;
    border-radius: 3px;
}

QScrollBar::handle:vertical {
    background-color: #2D201A;
    min-height: 28px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background-color: #FF5A22;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background-color: transparent;
    height: 6px;
    margin: 0px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal {
    background-color: #2D201A;
    min-width: 28px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #FF5A22;
}

/* Progress Bar */
QProgressBar {
    border: 1px solid #382E4D;
    border-radius: 7px;
    background-color: #1B1526;
    text-align: center;
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 700;
    height: 16px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF8C3B);
    border-radius: 6px;
}

/* Text Edit (Notes, Logs) */
QTextEdit, QPlainTextEdit {
    background-color: #171321;
    color: #E6E1F0;
    border: 1px solid #332747;
    border-radius: 10px;
    padding: 8px;
    font-size: 13px;
}

/* Video Player Controls & Sliders */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background-color: #282036;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF8C3B);
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 2px solid #FF5528;
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background-color: #FF8F55;
    border-color: #FFFFFF;
}

/* Play Control Buttons */
QPushButton.PlayerCtrlBtn {
    background-color: #221B2F;
    border: 1px solid #3B2E50;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 700;
    padding: 8px 14px;
    border-radius: 8px;
}

QPushButton.PlayerCtrlBtn:hover {
    background-color: #FF4D26;
    border-color: #FF7043;
}

/* Guide / Tutorial Cards */
QFrame.GuideCard {
    background-color: #1A1524;
    border: 1px solid #2F2440;
    border-radius: 14px;
    padding: 20px;
}

QFrame.GuideCard:hover {
    border-color: #FF6633;
    background-color: #1F192C;
}

QLabel.GuideStepBadge {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF7830);
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 800;
    border-radius: 6px;
    padding: 3px 9px;
}

QLabel.GuideTitle {
    font-size: 16px;
    font-weight: 800;
    color: #FFFFFF;
}

QLabel.GuideDesc {
    color: #C0B5D1;
    font-size: 13px;
    line-height: 1.6;
}

/* Status Bar */
QStatusBar {
    background-color: #14101B;
    color: #8C819F;
    border-top: 1px solid #231B2F;
    font-size: 11px;
}

/* ====================================================================
   Modern Glassmorphic Crimson & Dark MessageBox & Dialogs
   ==================================================================== */
QMessageBox {
    background-color: #181324;
    border: 1.5px solid #3E2F54;
    border-radius: 14px;
}

QMessageBox QLabel {
    color: #F8F5FC !important;
    background-color: transparent;
    font-size: 13.5px;
    font-weight: 500;
    line-height: 1.6;
    padding: 6px 12px;
    min-width: 320px;
}

QMessageBox QLabel#qt_msgbox_label {
    color: #FFFFFF !important;
    font-size: 14.5px;
    font-weight: 700;
}

QMessageBox QLabel#qt_msgbox_informativelabel {
    color: #DDD4EE !important;
    font-size: 13px;
    font-weight: 500;
}

QMessageBox QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4528, stop:1 #FF7A33);
    color: #FFFFFF !important;
    font-size: 13px;
    font-weight: 700;
    padding: 8px 26px;
    border-radius: 9px;
    border: 1px solid #FFA566;
    min-width: 85px;
    min-height: 24px;
}

QMessageBox QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5C40, stop:1 #FF8F4D);
    border: 1.5px solid #FFFFFF;
}

QMessageBox QPushButton:pressed {
    background: #E6381C;
    border: 1px solid #FF7A33;
}

QMessageBox QPushButton:focus {
    outline: none;
    border: 1.5px solid #FFA566;
}

/* Tooltips */
QToolTip {
    background-color: #231B32;
    color: #FFFFFF;
    border: 1px solid #FF6E38;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 600;
}

/* Context Menus */
QMenu {
    background-color: #1E1729;
    color: #F5F3F7;
    border: 1px solid #3B2E52;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 6px;
}

QMenu::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4528, stop:1 #FF7A33);
    color: #FFFFFF;
}

/* Episode Grid Chips */
QPushButton.EpChipSelected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF4528, stop:1 #FF8038);
    color: #FFFFFF;
    font-weight: 800;
    font-size: 12px;
    border: 1px solid #FF7043;
    border-radius: 8px;
}
QPushButton.EpChipSelected:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF5A3D, stop:1 #FF9452);
}
QPushButton.EpChipNormal {
    background-color: #20182E;
    color: #A699BD;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid #36274D;
    border-radius: 8px;
}
QPushButton.EpChipNormal:hover {
    background-color: #2E2242;
    color: #FFFFFF;
    border-color: #553E78;
}
QPushButton.EpChipDownloaded {
    background-color: #172B20;
    color: #4ADE80;
    font-weight: 700;
    font-size: 12px;
    border: 1px solid #23543A;
    border-radius: 8px;
}
QPushButton.EpChipDownloaded:hover {
    background-color: #213C2D;
    color: #86EFAC;
    border-color: #34D399;
}

/* Range Tab Buttons */
QPushButton.RangeTabBtn {
    background-color: #181224;
    color: #A69ABF;
    font-size: 11.5px;
    font-weight: 600;
    border: 1px solid #312347;
    border-radius: 6px;
    padding: 4px 10px;
}
QPushButton.RangeTabBtn:hover {
    background-color: #261B3B;
    color: #FFFFFF;
    border-color: #473266;
}
QPushButton.RangeTabBtn.active {
    background-color: #362452;
    color: #FFFFFF;
    font-weight: 700;
    border: 1px solid #5C3A8C;
}
"""
