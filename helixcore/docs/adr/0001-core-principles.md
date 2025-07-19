# ADR-0001: Core Architecture Principles

Date: 2025-01-19
Status: Accepted

## Context

HelixCore is designed to address the unique challenges of interdisciplinary R&D pipelines that span wet-lab experiments, AI algorithms, and computational simulations. Traditional workflow orchestration systems fall short in several key areas:

1. **Static Pipelines**: Most systems require predefined DAGs that cannot adapt to intermediate results
2. **Poor Failure Handling**: Loss of progress when workflows fail, requiring complete re-execution
3. **Monolithic Design**: Difficulty in adding new algorithms without modifying core system
4. **Limited Observability**: Insufficient visibility into distributed algorithm execution
5. **No Human Integration**: Cannot incorporate experimental validation mid-workflow

## Decision

We will adopt the following core principles:

### 1. Agents over Pipelines

**We will use LLM-powered agents for dynamic workflow orchestration instead of static pipeline definitions.**

Rationale:
- Research is exploratory and non-linear by nature
- Agents can adapt plans based on intermediate results
- Human expertise can be incorporated through agent reasoning
- Failed experiments lead to learning, not just retry

Implementation:
- Three-agent system: Planner → Executor → Critic
- AutoGen framework for multi-agent coordination
- Agents communicate through structured messages
- Each agent has specific capabilities and responsibilities

### 2. Durable Execution via Temporal

**We will use Temporal for workflow orchestration to ensure fault tolerance and replay capabilities.**

Rationale:
- R&D workflows can run for days or weeks
- System failures should not lose progress
- Need ability to update workflow logic without losing in-flight executions
- Experimental results may trigger workflow versioning

Implementation:
- Workflows defined as code with `@workflow.defn` decorator
- Automatic state persistence and replay on failure
- Signal handlers for human-in-the-loop integration
- Continue-as-new for version updates

### 3. Contract-Based Microservices

**Every algorithm will be a standalone microservice with a standardized manifest declaring its contract.**

Rationale:
- Algorithms developed by different teams/languages
- Need clear interface definitions for composition
- Resource requirements vary significantly
- Licensing and IP considerations

Implementation:
- `manifest.yaml` required for each algorithm
- gRPC service interface with standard methods
- Self-registration with Plugin Registry
- Container-based deployment

### 4. Observability First

**All components will emit structured telemetry data from inception.**

Rationale:
- Distributed systems require comprehensive observability
- Research requires audit trails and reproducibility
- Performance optimization needs baseline metrics
- Debugging complex workflows requires tracing

Implementation:
- OpenTelemetry instrumentation in all services
- Structured logging with correlation IDs
- Prometheus metrics for monitoring
- Distributed tracing for request flow

## Consequences

### Positive

1. **Flexibility**: Agents can adapt to changing research requirements
2. **Reliability**: Temporal ensures no loss of progress
3. **Extensibility**: New algorithms added without core changes
4. **Debuggability**: Comprehensive observability aids troubleshooting
5. **Scalability**: Microservices scale independently

### Negative

1. **Complexity**: Multi-agent systems harder to reason about
2. **Latency**: Agent deliberation adds overhead
3. **Cost**: LLM usage for planning incurs API costs
4. **Learning Curve**: Temporal and agent concepts require training

### Neutral

1. **Technology Lock-in**: Commitment to Temporal and AutoGen
2. **Infrastructure Requirements**: Need Kubernetes for production
3. **Development Overhead**: Manifest files and service contracts

## Alternatives Considered

### Alternative 1: Traditional DAG-based Workflow (Airflow/Prefect)

Rejected because:
- Cannot handle dynamic workflow adaptation
- Limited support for long-running workflows
- Poor integration with human-in-the-loop

### Alternative 2: Serverless Functions (Step Functions/Cloud Workflows)

Rejected because:
- Vendor lock-in concerns
- Limited support for stateful workflows
- Difficult to run on-premises

### Alternative 3: Custom Orchestration Engine

Rejected because:
- Massive development effort
- Would reinvent many Temporal features
- Maintenance burden

## References

- [Temporal Documentation](https://docs.temporal.io)
- [AutoGen: Multi-Agent Conversation Framework](https://github.com/microsoft/autogen)
- [The Twelve-Factor App](https://12factor.net/)
- [Domain-Driven Design by Eric Evans](https://www.domainlanguage.com/ddd/)
- [OpenTelemetry Specification](https://opentelemetry.io/docs/)