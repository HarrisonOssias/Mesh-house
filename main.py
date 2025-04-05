import sys
import serial
import serial.tools.list_ports
import datetime
import re
import random
from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QHBoxLayout,
    QApplication, QWidget, QVBoxLayout, QLabel, QGraphicsScene,
    QGraphicsView, QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsLineItem,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtGui import QBrush, QColor, QPen, QPainter
from PySide6.QtCore import QTimer, Qt, QPointF, QRectF
import math

# CONFIG
BAUDRATE = 115200
NODE_RADIUS = 30
CENTER_POS = QPointF(450, 300)
MAX_NODES = 12
INACTIVE_TIMEOUT = 15  # seconds

SERIAL_PORT = 'COM5'

class MessageDialog(QDialog):
    # Initializes the message dialog window that displays all messages received by a specific node.
    def __init__(self, node_addr, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Messages from {node_addr[-4:]}")
        self.resize(400, 300)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Time", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

    # Adds a new message to the dialog's table view for the corresponding node.
    def add_message(self, timestamp, message):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(timestamp))
        self.table.setItem(row, 1, QTableWidgetItem(message))
        self.table.scrollToBottom()

class MeshVisualizer(QWidget):
    # Initializes the main mesh visualizer UI, including scene setup, serial port connection, and timer configuration.
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mesh Network Live Map")
        self.resize(1000, 700)

        self.layout = QVBoxLayout(self)
        self.label = QLabel("Live Mesh Topology")
        self.layout.addWidget(self.label)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints() | QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.layout.addWidget(self.view)

        # Serial command input UI
        self.input_bar = QLineEdit()
        self.send_btn = QPushButton("Send")
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_bar)
        input_row.addWidget(self.send_btn)
        self.layout.addLayout(input_row)

        self.send_btn.clicked.connect(self.send_serial_command)

        # This opens the serial port for communication with the mesh leader device.
        self.serial = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)

        # Timer that regularly checks the serial port for new incoming messages.
        self.timer = QTimer()
        self.timer.timeout.connect(self.read_serial)
        self.timer.start(100)

        # Timer that checks whether nodes are still active based on the last time they sent a message.
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_node_activity)
        self.status_timer.start(1000)

        # This label displays the result of any command sent through the input bar for 5 seconds.
        self.command_response_label = QLabel()
        self.command_response_label.setStyleSheet("background-color: white; color: black; padding: 4px;")
        self.command_response_label.hide()
        self.command_response_timer = QTimer()
        self.command_response_timer.setSingleShot(True)
        self.command_response_timer.timeout.connect(self.command_response_label.hide)
        self.layout.addWidget(self.command_response_label)

        self.nodes = {}         # addr -> (ellipse, label)
        self.positions = {}     # addr -> QPointF
        self.edges = {}         # addr -> QGraphicsLineItem
        self.center_node = None
        self.message_logs = {}  # addr -> [(timestamp, message)]
        self.dialogs = {}       # addr -> MessageDialog
        self.last_seen = {}     # addr -> datetime

        # Add leader immediately for visualization
        self.leader_addr = "fd58:47f8:cd8:54c4:0:ff:fe00:fc00"
        self.add_node(self.leader_addr)

    # Continuously reads incoming lines from the serial port and passes them to the handler while displaying them in the UI.
    def read_serial(self):
        lines = []
        try:
            while self.serial.in_waiting:
                line = self.serial.readline().decode(errors='ignore').strip()
                if line:
                    lines.append(line)
                    self.handle_line(line)
            if lines:
                self.command_response_label.setText("\n".join(lines))
                self.command_response_label.show()
                self.command_response_timer.start(5000)
        except Exception as e:
            print(f"Serial error: {e}")

    # Parses a serial input line to extract the sender address and message, and creates simulated nodes if applicable.
    def handle_line(self, line):
        match = re.search(r"from ([\da-f:]+).*? (.+)$", line)
        if match:
            node_addr = match.group(1)
            message = match.group(2).strip()

            # PATCH: Simulate unique node using custom ID
            if message.lower().startswith("simulate:"):
                parts = message.split(None, 1)
                if len(parts) == 2:
                    sim_id = parts[0].split(":")[1]
                    node_addr = f"fd58:sim::{sim_id}"
                    message = parts[1]

            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            self.add_node(node_addr)
            self.add_message(node_addr, timestamp, message)
            self.last_seen[node_addr] = datetime.datetime.now()

    # Creates and places a visual node on the scene if it doesn't already exist. Leader is placed at center, others in a circle.
    def add_node(self, addr):
        if addr not in self.nodes:
            if self.center_node is None:
                pos = CENTER_POS
                self.center_node = addr
            else:
                angle = len(self.nodes) * (360 / MAX_NODES)
                radius = 200
                x = CENTER_POS.x() + radius * math.cos(math.radians(angle))
                y = CENTER_POS.y() + radius * math.sin(math.radians(angle))
                pos = QPointF(x, y)

            node = QGraphicsEllipseItem(0, 0, NODE_RADIUS, NODE_RADIUS)
            color = "orange" if addr == self.center_node else "skyblue"
            node.setBrush(QBrush(QColor(color)))
            node.setPos(pos)
            node.setFlag(QGraphicsEllipseItem.ItemIsSelectable)
            node.setFlag(QGraphicsEllipseItem.ItemIsMovable)
            node.setData(0, addr)

            label = QGraphicsTextItem(addr[-4:])
            label.setPos(pos + QPointF(NODE_RADIUS + 5, -5))

            self.scene.addItem(node)
            self.scene.addItem(label)

            node.mousePressEvent = self.make_node_click_handler(addr)

            self.nodes[addr] = (node, label)
            self.positions[addr] = pos

            if addr != self.center_node:
                self.draw_connection(addr)

    # Draws or updates a visual line between a child node and the center (leader) node.
    def draw_connection(self, addr):
        if self.center_node is None or addr == self.center_node:
            return
        src = self.positions[addr]
        dst = self.positions[self.center_node]

        line = QGraphicsLineItem(src.x() + NODE_RADIUS/2, src.y() + NODE_RADIUS/2,
                                 dst.x() + NODE_RADIUS/2, dst.y() + NODE_RADIUS/2)
        pen = QPen(QColor("lime"))
        pen.setWidth(2)
        line.setPen(pen)

        if addr in self.edges:
            self.scene.removeItem(self.edges[addr])
        self.edges[addr] = line
        self.scene.addItem(line)

    # Adds a message to the node's message history and updates the corresponding dialog if it's open.
    def add_message(self, addr, timestamp, message):
        if addr not in self.message_logs:
            self.message_logs[addr] = []
        self.message_logs[addr].append((timestamp, message))

        if addr in self.dialogs:
            self.dialogs[addr].add_message(timestamp, message)

    # Sends a raw string command over the serial port to the mesh device.
    def send_command(self, command: str):
        if self.serial.is_open:
            self.serial.write((command + '\r\n').encode())
            print(f"Sent: {command}")

    # Triggered when the Send button is clicked; fetches text from the input bar and sends it using send_command.
    def send_serial_command(self):
        command = self.input_bar.text().strip()
        if command:
            self.send_command(command)
            self.input_bar.clear()

    # Checks if nodes have been inactive for too long and updates their color accordingly.
    def check_node_activity(self):
        now = datetime.datetime.now()
        for addr, (node, _) in self.nodes.items():
            if addr == self.center_node:
                continue
            last_time = self.last_seen.get(addr)
            if last_time:
                delta = (now - last_time).total_seconds()
                if delta > INACTIVE_TIMEOUT:
                    node.setBrush(QBrush(QColor("red")))
                else:
                    node.setBrush(QBrush(QColor("skyblue")))

    # Returns an event handler function that opens the node's message dialog on click.
    def make_node_click_handler(self, addr):
        def handler(event):
            if addr not in self.dialogs:
                dlg = MessageDialog(addr)
                self.dialogs[addr] = dlg
                for timestamp, msg in self.message_logs.get(addr, []):
                    dlg.add_message(timestamp, msg)
                dlg.show()
            else:
                self.dialogs[addr].raise_()
                self.dialogs[addr].activateWindow()
        return handler

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = MeshVisualizer()
    viewer.show()
    sys.exit(app.exec())
