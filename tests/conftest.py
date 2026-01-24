import logging
import pytest
import sys

@pytest.fixture(autouse=True, scope="session")
def configure_pytest_logging():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logging.getLogger().handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    # Explicitly set the 'nmea2000' logger and all its children to DEBUG
    nmea_logger = logging.getLogger('nmea2000')
    nmea_logger.setLevel(logging.DEBUG)
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith('nmea2000.') and isinstance(logger, logging.Logger):
            logger.setLevel(logging.DEBUG)
            # Ensure each logger has a StreamHandler to sys.stdout
            if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                logger.addHandler(handler)
    return None
