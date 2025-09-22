import sys
import time
import statistics
from collections import deque
from typing import Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QLabel, 
                             QVBoxLayout, QGridLayout, QPushButton, QCheckBox,
                             QScrollArea, QFileDialog)
import pyqtgraph as pg

class LatencyDataPoint:
    def __init__(self, timestamp: float, stage: str, latency: float):
        self.timestamp = timestamp
        self.stage = stage
        self.latency = latency

class LatencyMonitor(QObject):
    """Monitors and tracks latency across different stages of the system"""
    
    # Signals for real-time updates
    latency_updated = pyqtSignal(str, float)  # stage, latency
    performance_alert = pyqtSignal(str, float)  # stage, threshold_exceeded
    
    def __init__(self, history_size: int = 1000):
        super().__init__()
        self.history_size = history_size
        self.latency_history: Dict[str, deque] = {
            'network_send': deque(maxlen=history_size),
            'network_receive': deque(maxlen=history_size),
            'fpga_processing': deque(maxlen=history_size),
            'command_execution': deque(maxlen=history_size),
            'total_round_trip': deque(maxlen=history_size),
            'frame_processing': deque(maxlen=history_size),
            'display_update': deque(maxlen=history_size)
        }
        
        self.stage_timers: Dict[str, float] = {}
        self.alert_thresholds = {
            'network_send': 50.0,      # ms
            'network_receive': 50.0,   # ms
            'fpga_processing': 100.0, # ms
            'command_execution': 200.0, # ms
            'total_round_trip': 500.0, # ms
            'frame_processing': 100.0, # ms
            'display_update': 33.0     # ms (30 FPS target)
        }
    
    def start_timer(self, stage: str):
        """Start timing a specific stage"""
        self.stage_timers[stage] = time.perf_counter()
    
    def end_timer(self, stage: str) -> float:
        """End timing a stage and return latency in milliseconds"""
        if stage not in self.stage_timers:
            return 0.0
        
        start_time = self.stage_timers.pop(stage)
        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000.0
        
        # Store in history
        if stage in self.latency_history:
            self.latency_history[stage].append(LatencyDataPoint(end_time, stage, latency_ms))
        
        # Emit signals
        self.latency_updated.emit(stage, latency_ms)
        
        # Check for performance alerts
        if stage in self.alert_thresholds and latency_ms > self.alert_thresholds[stage]:
            self.performance_alert.emit(stage, latency_ms)
        
        return latency_ms
    
    def get_statistics(self, stage: str) -> Dict[str, float]:
        """Get statistical summary for a stage"""
        if stage not in self.latency_history or not self.latency_history[stage]:
            return {'mean': 0.0, 'median': 0.0, 'p95': 0.0, 'p99': 0.0, 'max': 0.0, 'min': 0.0}
        
        latencies = [dp.latency for dp in self.latency_history[stage]]
        return {
            'mean': statistics.mean(latencies),
            'median': statistics.median(latencies),
            'p95': statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
            'p99': statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies),
            'max': max(latencies),
            'min': min(latencies)
        }
    
    def get_recent_latencies(self, stage: str, count: int = 100) -> List[float]:
        """Get recent latency values for a stage"""
        if stage not in self.latency_history:
            return []
        return [dp.latency for dp in list(self.latency_history[stage])[-count:]]

class LatencyVisualizationWidget(QWidget):
    """Main widget for displaying real-time latency information"""
    
    def __init__(self, latency_monitor: LatencyMonitor):
        super().__init__()
        self.latency_monitor = latency_monitor
        self.setup_ui()
        self.setup_connections()
        
        # Update timer for real-time display
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_displays)
        self.update_timer.start(100)  # Update every 100ms
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Real-Time Latency Monitor")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(title)
        
        # Create tabs for different views
        from PyQt6.QtWidgets import QTabWidget
        self.tab_widget = QTabWidget()
        
        # Real-time graphs tab
        self.realtime_tab = QWidget()
        self.setup_realtime_tab()
        self.tab_widget.addTab(self.realtime_tab, "Real-time Graphs")
        
        # Statistics tab
        self.stats_tab = QWidget()
        self.setup_stats_tab()
        self.tab_widget.addTab(self.stats_tab, "Statistics")
        
        # Alerts tab
        self.alerts_tab = QWidget()
        self.setup_alerts_tab()
        self.tab_widget.addTab(self.alerts_tab, "Performance Alerts")
        
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)
    
    def setup_realtime_tab(self):
        """Setup real-time latency graphs"""
        layout = QVBoxLayout()
        
        # Create single plot widget
        self.plot_widget = pg.PlotWidget()
        self.main_plot = self.plot_widget
        
        # Set up plot appearance
        self.main_plot.setBackground('k')  # Black background
        self.main_plot.showGrid(x=True, y=True, alpha=0.3)
        self.main_plot.setLabel('left', 'Latency (ms)')
        self.main_plot.setLabel('bottom', 'Time')
        self.main_plot.setTitle("Round-trip Latency")
        
        # Create plot curves for each stage
        self.plot_curves = {}
        colors = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#34495e']
        
        for i, stage in enumerate(self.latency_monitor.latency_history.keys()):
            color = colors[i % len(colors)]
            self.plot_curves[stage] = self.main_plot.plot(
                pen=pg.mkPen(color=color, width=2),
                name=stage.replace('_', ' ').title()
            )
            # Add initial data point to ensure legend appears
            self.plot_curves[stage].setData([0], [0])
        
        # Add legend with explicit styling and positioning
        legend = self.main_plot.addLegend()
        legend.setLabelTextColor('w')  # White text
        legend.setLabelTextSize('12pt')  # Larger text
        
        layout.addWidget(self.plot_widget)
        
        # Add export button
        export_btn = QPushButton("Export Statistics")
        export_btn.clicked.connect(self.export_statistics)
        layout.addWidget(export_btn)
        
        self.realtime_tab.setLayout(layout)
    
    def setup_stats_tab(self):
        """Setup clean statistics display using QTableWidget"""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Create table widget
        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        from PyQt6.QtCore import Qt
        self.stats_table = QTableWidget()
        
        # Set up table structure
        stages = list(self.latency_monitor.latency_history.keys())
        self.stats_table.setRowCount(len(stages))
        self.stats_table.setColumnCount(7)
        
        # Set headers
        headers = ['Stage', 'Mean', 'Median', 'P95', 'P99', 'Max', 'Min']
        self.stats_table.setHorizontalHeaderLabels(headers)
        
        # Style the table
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        # Don't set selection behavior for now - it's not critical
        
        # Populate with stage names
        for i, stage in enumerate(stages):
            stage_item = QTableWidgetItem(stage.replace('_', ' ').title())
            stage_item.setFlags(stage_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.stats_table.setItem(i, 0, stage_item)
            
            # Initialize other cells
            for j in range(1, 7):
                item = QTableWidgetItem("0.0")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(i, j, item)
        
        # Store references to updateable cells
        self.stats_cells = {}
        for i, stage in enumerate(stages):
            self.stats_cells[stage] = {}
            for j, stat in enumerate(['mean', 'median', 'p95', 'p99', 'max', 'min'], 1):
                self.stats_cells[stage][stat] = self.stats_table.item(i, j)
        
        layout.addWidget(self.stats_table)
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.clear_stats_btn = QPushButton("Clear")
        self.clear_stats_btn.clicked.connect(self.clear_statistics)
        self.export_stats_btn = QPushButton("Export")
        self.export_stats_btn.clicked.connect(self.export_statistics)
        
        button_layout.addWidget(self.clear_stats_btn)
        button_layout.addWidget(self.export_stats_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        self.stats_tab.setLayout(layout)
    
    def setup_alerts_tab(self):
        """Setup performance alerts display"""
        layout = QVBoxLayout()
        
        # Alerts list
        self.alerts_list = QWidget()
        self.alerts_layout = QVBoxLayout()
        self.alerts_list.setLayout(self.alerts_layout)
        
        # Scroll area for alerts
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.alerts_list)
        scroll_area.setWidgetResizable(True)
        
        layout.addWidget(scroll_area)
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.clear_alerts_btn = QPushButton("Clear Alerts")
        self.clear_alerts_btn.clicked.connect(self.clear_alerts)
        self.alert_threshold_btn = QPushButton("Configure Thresholds")
        self.alert_threshold_btn.clicked.connect(self.configure_thresholds)
        
        button_layout.addWidget(self.clear_alerts_btn)
        button_layout.addWidget(self.alert_threshold_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        self.alerts_tab.setLayout(layout)
    
    def setup_connections(self):
        """Connect signals from latency monitor"""
        self.latency_monitor.latency_updated.connect(self.on_latency_updated)
        self.latency_monitor.performance_alert.connect(self.on_performance_alert)
    
    def on_latency_updated(self, stage: str, latency: float):
        """Handle latency updates"""
        # Update real-time plots
        self.update_plot_data(stage, latency)
    
    def on_performance_alert(self, stage: str, latency: float):
        """Handle performance alerts"""
        self.add_alert(stage, latency)
    
    def update_plot_data(self, stage: str, latency: float):
        """Update plot data for a stage"""
        current_time = time.time()
        
        if stage in self.plot_curves:
            # Get recent data
            recent_data = self.latency_monitor.get_recent_latencies(stage, 100)
            if recent_data:
                # Create time axis
                time_axis = np.linspace(current_time - len(recent_data) * 0.1, current_time, len(recent_data))
                self.plot_curves[stage].setData(time_axis, recent_data)
    
    def update_displays(self):
        """Update all displays (called by timer)"""
        self.update_statistics()
    
    def update_statistics(self):
        """Update statistics table with current data"""
        for stage in self.latency_monitor.latency_history.keys():
            if stage in self.stats_cells:
                stats = self.latency_monitor.get_statistics(stage)
                for stat_name, value in stats.items():
                    if stat_name in self.stats_cells[stage]:
                        cell = self.stats_cells[stage][stat_name]
                        cell.setText(f"{value:.1f}")
    
    def add_alert(self, stage: str, latency: float):
        """Add a performance alert"""
        alert_widget = QWidget()
        alert_layout = QHBoxLayout()
        
        # Alert icon and text
        alert_text = QLabel(f"⚠️ {stage.replace('_', ' ').title()}: {latency:.2f}ms")
        alert_text.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 5px;")
        
        # Timestamp
        timestamp = QLabel(time.strftime("%H:%M:%S"))
        timestamp.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        
        alert_layout.addWidget(alert_text)
        alert_layout.addStretch()
        alert_layout.addWidget(timestamp)
        
        alert_widget.setLayout(alert_layout)
        self.alerts_layout.addWidget(alert_widget)
    
    def clear_statistics(self):
        """Clear all statistics"""
        for stage in self.latency_monitor.latency_history.keys():
            self.latency_monitor.latency_history[stage].clear()
    
    def clear_alerts(self):
        """Clear all alerts"""
        while self.alerts_layout.count():
            child = self.alerts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    def export_statistics(self):
        """Export statistics to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Statistics", "", "CSV Files (*.csv)"
        )
        if filename:
            self.save_statistics_to_csv(filename)
    
    def save_statistics_to_csv(self, filename: str):
        """Save statistics to CSV file"""
        import csv
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Stage', 'Mean (ms)', 'Median (ms)', 'P95 (ms)', 'P99 (ms)', 'Max (ms)', 'Min (ms)'])
            
            for stage in self.latency_monitor.latency_history.keys():
                stats = self.latency_monitor.get_statistics(stage)
                writer.writerow([
                    stage,
                    stats['mean'],
                    stats['median'],
                    stats['p95'],
                    stats['p99'],
                    stats['max'],
                    stats['min']
                ])
    
    def configure_thresholds(self):
        """Open threshold configuration dialog"""
        # TODO: Implement threshold configuration dialog
        pass
