#!/usr/bin/env python3
"""
Web Server Startup Script

This script starts the web dashboard server for the Discord selfbot logger.
Run this alongside main.py to access the web interface.
"""

import os
import sys
import logging
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent / 'backend'
sys.path.insert(0, str(backend_dir))

from web_server import app, socketio, initialize_components
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Start the web server"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    try:
        # Initialize web server components
        logger.info("Initializing web server components...")
        initialize_components()
        
        # Web server settings from environment variables
        host = os.getenv('WEB_HOST', '127.0.0.1')
        port = int(os.getenv('WEB_PORT', 5002))
        debug = os.getenv('WEB_DEBUG', 'false').lower() == 'true'
        
        logger.info(f"Starting Discord Selfbot Logger Web Dashboard...")
        logger.info(f"Server will be available at: http://{host}:{port}")
        logger.info(f"Debug mode: {debug}")
        
        # Start the server
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,  # Disable reloader to prevent issues
            log_output=True
        )
        
    except KeyboardInterrupt:
        logger.info("Web server stopped by user")
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()