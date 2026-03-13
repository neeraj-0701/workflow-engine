"""
Configurable Workflow Decision Platform
Main FastAPI application entry point
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import workflow_router, health_router
from app.services.config_loader import ConfigLoader
from app.services.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    logger.info("🚀 Starting Configurable Workflow Decision Platform...")
    
    # Initialize database
    await init_db()
    logger.info("✅ Database initialized")
    
    # Load workflow configurations
    config_loader = ConfigLoader()
    app.state.config_loader = config_loader
    loaded = config_loader.load_all()
    logger.info(f"✅ Loaded {len(loaded)} workflow configurations: {list(loaded.keys())}")
    
    yield
    
    logger.info("🛑 Shutting down Workflow Decision Platform...")


app = FastAPI(
    title="Configurable Workflow Decision Platform",
    description="""
    A powerful, config-driven workflow engine that processes requests through 
    configurable multi-step workflows with rule evaluation, state management, 
    audit logging, and failure handling.
    
    ## Key Features
    - 🔧 **Config-driven**: Define workflows in YAML without code changes
    - 📋 **Rule Engine**: Flexible condition evaluation with AND/OR logic
    - 🔄 **State Management**: Full workflow state persistence
    - 📝 **Audit Logging**: Complete decision traceability
    - 🔁 **Retry Logic**: Automatic retry with exponential backoff
    - 🔑 **Idempotency**: Duplicate request protection
    - 🌐 **External Simulation**: Mock external dependency calls
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(workflow_router, prefix="", tags=["Workflows"])


@app.get("/", tags=["Root"])
async def root():
    """Platform overview and available workflows."""
    from app.services.config_loader import ConfigLoader
    config_loader = ConfigLoader()
    configs = config_loader.load_all()
    return {
        "platform": "Configurable Workflow Decision Platform",
        "version": "1.0.0",
        "status": "running",
        "available_workflows": list(configs.keys()),
        "endpoints": {
            "process_request": "POST /process-request",
            "workflow_status": "GET /workflow-status/{workflow_id}",
            "audit_log": "GET /audit-log/{workflow_id}",
            "list_workflows": "GET /workflows",
            "docs": "GET /docs",
        },
    }
