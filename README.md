# Carton MCP

A Zettelkasten-style knowledge management system that provides both a **core library** for concept management and an **MCP server** for agent-driven knowledge operations.

## Overview

Carton creates a dual-storage concept management system where ideas are stored as both Neo4j graph nodes and GitHub markdown files. The system auto-discovers relationships from text descriptions, manages missing concepts, and provides sophisticated graph querying capabilities.

This package provides both a **core library** for direct concept management and an **MCP server** for agent consumption.

## Core Library Features

### 🏗️ CartOnUtils - Core Business Logic
- **Neo4j Graph Operations**: Execute read-only Cypher queries on :Wiki namespace
- **Concept Network Analysis**: Get connected concepts with 1-3 hop relationship depth  
- **Missing Concept Management**: Detect, track, and auto-create missing concepts
- **Duplicate Detection**: Find similar concepts using textual similarity analysis
- **GitHub Integration**: Commit concept files and missing_concepts.md to repository

### ⚙️ ConceptConfig - Configuration Management
- **Dual Storage Setup**: Configure both GitHub (PAT, repo) and Neo4j (URI, credentials) 
- **HEAVEN Data Integration**: Uses HEAVEN_DATA_DIR for local concept storage
- **Environment-based Config**: Loads settings from environment variables

### 📝 Add Concept Tool - Content Creation
- **Auto-linking**: Discovers concept mentions in descriptions and creates relationships
- **Relationship Inference**: Creates bidirectional links and inverse relationships
- **File Generation**: Creates structured markdown files in wiki/concepts/ directory
- **Neo4j Integration**: Stores concepts as nodes with normalized properties

## MCP Server Features

### 🛠️ 7 MCP Tools
- **add_concept**: Create concepts with auto-relationship discovery
- **query_wiki_graph**: Execute read-only Cypher queries on :Wiki namespace  
- **get_concept_network**: Explore concept relationships with depth control (1-3 hops)
- **list_missing_concepts**: Show concepts referenced but not yet created
- **calculate_missing_concepts**: Scan all concepts and update missing_concepts.md
- **create_missing_concepts**: Bulk create missing concepts with AI descriptions
- **deduplicate_concepts**: Find similar concepts using similarity thresholds

### 📋 4 MCP Prompts
- **add_user_thought**: Capture user quotes verbatim with topic attribution
- **update_known_concept**: Update existing concepts while preserving relationships
- **update_user_thought_train_emergently**: Track how thoughts evolved into insights
- **sync_after_update_known_concept**: Create sync concepts for version control

## Installation

[Installation instructions pending PyPI publication]

## Architecture

**Dual Storage Model:**
- **GitHub**: Markdown files in `wiki/concepts/` structure with auto-linking
- **Neo4j**: Graph database using `:Wiki` namespace with properties `n` (name), `d` (description), `c` (canonical), `t` (timestamp)

**Auto-Discovery System:**
- Scans concept descriptions for mentions of other concepts
- Creates `relates_to` relationships automatically
- Tracks missing concepts and generates creation templates
- Maintains bidirectional relationships and inverse inference

## Dependencies

- HEAVEN Framework for Neo4j utilities and base tool classes
- Neo4j Python driver for graph database operations
- GitHub integration for version control and wiki generation
- MCP protocol for agent tool exposure

## License

MIT License - see LICENSE file for details.