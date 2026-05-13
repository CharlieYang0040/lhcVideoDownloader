APP_STYLESHEET = """
* {
    font-family: "Malgun Gothic", "맑은 고딕", "Segoe UI", sans-serif;
    font-size: 13px;
    letter-spacing: 0px;
}

QMainWindow,
QWidget#Root {
    background-color: #0f1115;
    color: #e6e8eb;
}

QFrame#Panel {
    background-color: #171a20;
    border: 1px solid #2b313a;
    border-radius: 6px;
}

QFrame#AdvancedPanel {
    background-color: #14171c;
    border: 1px solid #29303a;
    border-radius: 4px;
}

QFrame#TaskRow {
    background-color: #171a20;
    border: 1px solid #2a3038;
    border-radius: 5px;
}

QLabel {
    color: #d7dce2;
    font-weight: 500;
}

QLabel#AppTitle {
    color: #f2f5f8;
    font-size: 20px;
    font-weight: 700;
}

QLabel#SectionTitle {
    color: #f2f5f8;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#MutedLabel {
    color: #8d98a6;
    font-size: 11px;
    font-weight: 500;
}

QLabel#TaskTitle {
    color: #f0f4f8;
    font-size: 12px;
    font-weight: 700;
}

QLabel#MetricsLabel {
    color: #aeb7c2;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    font-weight: 500;
}

QLabel#StatusBadge {
    background-color: #242a33;
    border: 1px solid #3a4250;
    border-radius: 4px;
    color: #cbd3dc;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
}

QLabel#StatusBadge[state="running"] {
    background-color: #12344a;
    border-color: #1b6f9f;
    color: #9fe2ff;
}

QLabel#StatusBadge[state="done"] {
    background-color: #163923;
    border-color: #2a7f45;
    color: #9ff0b5;
}

QLabel#StatusBadge[state="warning"] {
    background-color: #463313;
    border-color: #a8751a;
    color: #ffd28a;
}

QLabel#StatusBadge[state="error"] {
    background-color: #4a1919;
    border-color: #a43a3a;
    color: #ffaaa5;
}

QLineEdit,
QComboBox,
QSpinBox {
    min-height: 30px;
    padding: 4px 8px;
    background-color: #0f1217;
    border: 1px solid #323a45;
    border-radius: 4px;
    color: #e6e8eb;
    selection-background-color: #0e639c;
}

QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus {
    border-color: #2e9cdc;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #8f9aaa;
    margin-right: 8px;
}

QPushButton,
QToolButton {
    min-height: 30px;
    background-color: #252b34;
    border: 1px solid #343c48;
    border-radius: 4px;
    color: #e6e8eb;
    font-weight: 700;
    padding: 5px 12px;
}

QPushButton:hover,
QToolButton:hover {
    background-color: #303743;
    border-color: #46515f;
}

QPushButton:pressed,
QToolButton:pressed {
    background-color: #1d232b;
}

QPushButton#ActionBtn {
    background-color: #0e639c;
    border-color: #1579bd;
    color: #ffffff;
}

QPushButton#ActionBtn:hover {
    background-color: #1177bb;
}

QPushButton#SecondaryButton {
    background-color: #20262e;
    border-color: #343c48;
    color: #d8dee6;
}

QPushButton#DangerButton {
    background-color: #4a2325;
    border-color: #8a3b3d;
    color: #ffd6d2;
}

QPushButton#DangerButton:hover {
    background-color: #6a2e31;
}

QToolButton#IconButton {
    min-width: 30px;
    max-width: 30px;
    padding: 4px;
}

QToolButton#AdvancedToggle {
    background-color: transparent;
    border: none;
    color: #9fb4c8;
    font-weight: 700;
    padding: 4px 0px;
}

QToolButton#AdvancedToggle:hover {
    color: #d7ecff;
}

QCheckBox {
    color: #cdd5df;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    background-color: #0f1217;
    border: 1px solid #3a4350;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    background-color: #0e639c;
    border-color: #2e9cdc;
}

QListWidget {
    background-color: #101318;
    border: 1px solid #2a3038;
    border-radius: 6px;
    outline: none;
    padding: 6px;
}

QListWidget::item {
    margin: 4px;
}

QProgressBar {
    min-height: 7px;
    max-height: 7px;
    background-color: #252b33;
    border: none;
    border-radius: 3px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #1da6d8;
    border-radius: 3px;
}

QTextEdit {
    background-color: #090b0f;
    border: 1px solid #2a3038;
    border-radius: 4px;
    color: #dce3ea;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}

QMessageBox {
    background-color: #171a20;
}
"""


def refresh_style(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
