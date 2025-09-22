#!/usr/bin/env python3
"""
Test script for the latency monitor functionality.
This script can be run independently to test the latency monitoring system.
"""

import sys
import asyncio
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop

# Add the Software directory to the path so we can import our modules
sys.path.insert(0, '.')

from obi.gui.components.latency_monitor import LatencyMonitor, LatencyVisualizationWidget

async def test_latency_monitor():
    """Test the latency monitor with simulated delays"""
    print("Testing Latency Monitor...")
    
    # Create latency monitor
    monitor = LatencyMonitor()
    
    # Test basic timing functionality
    print("\n1. Testing basic timing...")
    monitor.start_timer('test_stage')
    await asyncio.sleep(0.1)  # Simulate 100ms delay
    latency = monitor.end_timer('test_stage')
    print(f"Measured latency: {latency:.2f}ms (expected ~100ms)")
    
    # Test multiple measurements
    print("\n2. Testing multiple measurements...")
    for i in range(5):
        monitor.start_timer('multiple_test')
        await asyncio.sleep(0.05)  # 50ms delay
        latency = monitor.end_timer('multiple_test')
        print(f"Measurement {i+1}: {latency:.2f}ms")
    
    # Test statistics
    print("\n3. Testing statistics...")
    stats = monitor.get_statistics('multiple_test')
    print(f"Statistics: {stats}")
    
    # Test recent latencies
    print("\n4. Testing recent latencies...")
    recent = monitor.get_recent_latencies('multiple_test', 3)
    print(f"Recent 3 latencies: {recent}")
    
    print("\nLatency monitor test completed successfully!")

def test_gui():
    """Test the GUI components"""
    print("Testing GUI components...")
    
    app = QApplication(sys.argv)
    
    # Create latency monitor
    monitor = LatencyMonitor()
    
    # Create visualization widget
    widget = LatencyVisualizationWidget(monitor)
    widget.show()
    
    # Simulate some latency data
    def simulate_data():
        import random
        stages = ['network_send', 'network_receive', 'fpga_processing', 'command_execution']
        for stage in stages:
            # Simulate realistic latency values
            latency = random.uniform(10, 200)  # 10-200ms
            monitor.start_timer(stage)
            time.sleep(latency / 1000)  # Convert to seconds
            measured = monitor.end_timer(stage)
            print(f"Simulated {stage}: {measured:.2f}ms")
    
    # Run simulation in a separate thread
    import threading
    sim_thread = threading.Thread(target=simulate_data)
    sim_thread.daemon = True
    sim_thread.start()
    
    print("GUI test started. Close the window to exit.")
    app.exec()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        test_gui()
    else:
        asyncio.run(test_latency_monitor())
