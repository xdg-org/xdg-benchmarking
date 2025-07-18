import os
import json
import time
from datetime import datetime
from typing import Dict, Any
from config import get_config
from logging_config import get_logger

logger = get_logger('health')

class HealthChecker:
    """Health check functionality for the XDG Dashboard"""

    def __init__(self):
        self.config = get_config()
        self.start_time = time.time()

    def check_data_availability(self) -> Dict[str, Any]:
        """Check if benchmark data is available"""
        try:
            runs_dir = self.config.RUNS_DIR
            if not os.path.exists(runs_dir):
                return {
                    'status': 'error',
                    'message': f'Results directory not found: {runs_dir}',
                    'runs_count': 0
                }

            runs = [d for d in os.listdir(runs_dir)
                   if os.path.isdir(os.path.join(runs_dir, d))]

            valid_runs = 0
            for run_id in runs:
                run_path = os.path.join(runs_dir, run_id)
                config_file = os.path.join(run_path, "config.json")
                results_file = os.path.join(run_path, "results.json")

                if os.path.exists(config_file) and os.path.exists(results_file):
                    try:
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                        with open(results_file, 'r') as f:
                            results = json.load(f)

                        if (config.get('run_id') == results.get('run_id') and
                            config.get('date') == results.get('date')):
                            valid_runs += 1
                    except (json.JSONDecodeError, KeyError):
                        continue

            return {
                'status': 'healthy' if valid_runs > 0 else 'warning',
                'message': f'Found {valid_runs} valid benchmark runs',
                'runs_count': valid_runs
            }

        except Exception as e:
            logger.error(f"Error checking data availability: {e}")
            return {
                'status': 'error',
                'message': f'Error checking data: {str(e)}',
                'runs_count': 0
            }

    def check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage('.')
            free_gb = free / (1024**3)

            if free_gb > 10:
                status = 'healthy'
            elif free_gb > 5:
                status = 'warning'
            else:
                status = 'error'

            return {
                'status': status,
                'message': f'{free_gb:.1f} GB free space available',
                'free_gb': free_gb
            }

        except Exception as e:
            logger.error(f"Error checking disk space: {e}")
            return {
                'status': 'error',
                'message': f'Error checking disk space: {str(e)}',
                'free_gb': 0
            }

    def check_memory_usage(self) -> Dict[str, Any]:
        """Check memory usage"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            if memory_percent < 80:
                status = 'healthy'
            elif memory_percent < 90:
                status = 'warning'
            else:
                status = 'error'

            return {
                'status': status,
                'message': f'Memory usage: {memory_percent:.1f}%',
                'memory_percent': memory_percent,
                'available_gb': memory.available / (1024**3)
            }

        except ImportError:
            return {
                'status': 'unknown',
                'message': 'psutil not available for memory monitoring',
                'memory_percent': 0
            }
        except Exception as e:
            logger.error(f"Error checking memory usage: {e}")
            return {
                'status': 'error',
                'message': f'Error checking memory: {str(e)}',
                'memory_percent': 0
            }

    def get_uptime(self) -> Dict[str, Any]:
        """Get application uptime"""
        uptime_seconds = time.time() - self.start_time
        uptime_hours = uptime_seconds / 3600

        return {
            'uptime_seconds': uptime_seconds,
            'uptime_hours': uptime_hours,
            'start_time': datetime.fromtimestamp(self.start_time).isoformat()
        }

    def get_full_health_status(self) -> Dict[str, Any]:
        """Get complete health status"""
        data_status = self.check_data_availability()
        disk_status = self.check_disk_space()
        memory_status = self.check_memory_usage()
        uptime = self.get_uptime()

        # Overall status
        statuses = [data_status['status'], disk_status['status'], memory_status['status']]
        if 'error' in statuses:
            overall_status = 'error'
        elif 'warning' in statuses:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'

        return {
            'status': overall_status,
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0',
            'uptime': uptime,
            'checks': {
                'data_availability': data_status,
                'disk_space': disk_status,
                'memory_usage': memory_status
            }
        }

# Global health checker instance
health_checker = HealthChecker()

def get_health_status() -> Dict[str, Any]:
    """Get current health status"""
    return health_checker.get_full_health_status()