import os
from typing import Optional

class Config:
    """Configuration class for the XDG Benchmarking Dashboard"""

    # Flask/Dash Configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

    # Server Configuration
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 8050))

    # Data Configuration
    RESULTS_DIR = os.environ.get('RESULTS_DIR', 'results')
    RUNS_DIR = os.path.join(RESULTS_DIR, 'runs')

    # Dashboard Configuration
    DASHBOARD_TITLE = "XDG Benchmarking Dashboard"
    DASHBOARD_SUBTITLE = "Accelerated Discretized Geometry Performance Analysis"

    # Chart Configuration
    CHART_HEIGHT = 400
    CHART_TEMPLATE = 'plotly_white'

    # Performance Configuration
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 4))
    TIMEOUT = int(os.environ.get('TIMEOUT', 120))

    # Logging Configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

    @classmethod
    def get_gunicorn_config(cls) -> dict:
        """Get Gunicorn configuration for production deployment"""
        return {
            'bind': f'{cls.HOST}:{cls.PORT}',
            'workers': cls.MAX_WORKERS,
            'timeout': cls.TIMEOUT,
            'worker_class': 'sync',
            'worker_connections': 1000,
            'max_requests': 1000,
            'max_requests_jitter': 50,
            'preload_app': True,
            'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s',
        }

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    LOG_LEVEL = 'WARNING'

    @classmethod
    def init_app(cls, app):
        """Initialize production-specific settings"""
        # Add production-specific middleware here if needed
        pass

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    RESULTS_DIR = 'test_results'

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config(config_name: Optional[str] = None) -> Config:
    """Get configuration based on environment"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    return config.get(config_name, config['default'])