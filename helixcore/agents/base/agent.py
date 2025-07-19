"""Base agent implementation for multi-agent system.

This module provides the abstract base class for all agents in the
HelixCore multi-agent reasoning layer.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class AgentMessage(BaseModel):
    """Message passed between agents."""
    
    sender: str = Field(..., description="Agent ID that sent the message")
    recipient: str = Field(..., description="Target agent ID")
    content: Dict[str, Any] = Field(..., description="Message payload")
    message_type: str = Field(..., description="Type of message")
    correlation_id: str = Field(..., description="ID to track message flow")
    timestamp: str = Field(..., description="ISO format timestamp")


class AgentState(BaseModel):
    """Agent state representation."""
    
    agent_id: str = Field(..., description="Unique agent identifier")
    status: str = Field("idle", description="Current agent status")
    memory: Dict[str, Any] = Field(default_factory=dict, description="Agent memory")
    conversation_history: List[AgentMessage] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base class for all HelixCore agents.
    
    This class provides the foundational structure for implementing
    agents that participate in the multi-agent reasoning system.
    Each agent has specific capabilities and can communicate with
    other agents to accomplish complex tasks.
    
    Attributes
    ----------
    agent_id : str
        Unique identifier for the agent.
    name : str
        Human-readable name for the agent.
    capabilities : List[str]
        List of capabilities this agent possesses.
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        capabilities: Optional[List[str]] = None,
    ) -> None:
        """Initialize the base agent.
        
        Parameters
        ----------
        agent_id : str
            Unique identifier for the agent.
        name : str
            Human-readable name for the agent.
        capabilities : Optional[List[str]], optional
            List of capabilities, by default None.
        """
        self.agent_id = agent_id
        self.name = name
        self.state = AgentState(
            agent_id=agent_id,
            capabilities=capabilities or [],
        )
        self.logger = logger.bind(agent_id=agent_id, agent_name=name)
        
    @abstractmethod
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Process an incoming message.
        
        This method must be implemented by all agents to handle
        incoming messages and generate appropriate responses.
        
        Parameters
        ----------
        message : AgentMessage
            The incoming message to process.
            
        Returns
        -------
        Optional[AgentMessage]
            Response message if applicable, None otherwise.
        """
        raise NotImplementedError("Subclasses must implement process_message()")
    
    @abstractmethod
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific task.
        
        This method defines how the agent executes its primary
        responsibilities based on its capabilities.
        
        Parameters
        ----------
        task : Dict[str, Any]
            The task specification to execute.
            
        Returns
        -------
        Dict[str, Any]
            The task execution results.
        """
        raise NotImplementedError("Subclasses must implement execute_task()")
    
    def update_memory(self, key: str, value: Any) -> None:
        """Update agent's memory.
        
        Parameters
        ----------
        key : str
            Memory key to update.
        value : Any
            Value to store.
        """
        self.state.memory[key] = value
        self.logger.debug("memory_updated", key=key)
    
    def get_memory(self, key: str, default: Any = None) -> Any:
        """Retrieve value from agent's memory.
        
        Parameters
        ----------
        key : str
            Memory key to retrieve.
        default : Any, optional
            Default value if key not found, by default None.
            
        Returns
        -------
        Any
            The stored value or default.
        """
        return self.state.memory.get(key, default)
    
    def add_to_history(self, message: AgentMessage) -> None:
        """Add message to conversation history.
        
        Parameters
        ----------
        message : AgentMessage
            Message to add to history.
        """
        self.state.conversation_history.append(message)
        
        # Keep history size manageable
        if len(self.state.conversation_history) > 100:
            self.state.conversation_history = self.state.conversation_history[-100:]
    
    def get_recent_history(self, count: int = 10) -> List[AgentMessage]:
        """Get recent conversation history.
        
        Parameters
        ----------
        count : int, optional
            Number of recent messages to retrieve, by default 10.
            
        Returns
        -------
        List[AgentMessage]
            Recent messages from history.
        """
        return self.state.conversation_history[-count:]
    
    def has_capability(self, capability: str) -> bool:
        """Check if agent has a specific capability.
        
        Parameters
        ----------
        capability : str
            Capability to check for.
            
        Returns
        -------
        bool
            True if agent has the capability, False otherwise.
        """
        return capability in self.state.capabilities
    
    def set_status(self, status: str) -> None:
        """Update agent status.
        
        Parameters
        ----------
        status : str
            New status value.
        """
        self.state.status = status
        self.logger.info("status_changed", new_status=status)
    
    async def initialize(self) -> None:
        """Initialize agent resources.
        
        Override this method to perform any async initialization
        required by the agent.
        """
        self.logger.info("agent_initialized")
    
    async def shutdown(self) -> None:
        """Clean up agent resources.
        
        Override this method to perform any cleanup required
        when the agent is shutting down.
        """
        self.logger.info("agent_shutdown")