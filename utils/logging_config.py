import logging
import os

def setup_logging():
    """Configure the logging system for GovGen."""
    # Create logger
    logger = logging.getLogger('govgen')
    logger.setLevel(logging.ERROR)  # Only log ERROR and above

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Console handler for ERROR and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler for ERROR and above
    log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'govgen.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

# Initialize logger
logger = setup_logging()