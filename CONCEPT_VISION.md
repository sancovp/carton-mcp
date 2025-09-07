# Idea Concepts MCP - Vision Document

## The Core Problem

As expressed by the founder:

> "I think im just realizing that i need a lot more structure overall but it's not that i need to make existing systems more complex, it might be that i need to take systems that work and employ them myself fully. For example, designing a core architecture and way that patterns should work before actually working on it."

> "I need a place that has all my ideas... and i have to be able to see them, and i'd like to chat with you about them so that you know what i know and we can go thru what to do. That's actually the entire idea. I want that."

The fundamental issue is the gap between having ideas and being able to work with them effectively:

> "the problem with heaven-bml github was i couldnt see it, then it got too expensive. Now i have a kanban i can see but im still not sure how to organize ideas in it. So now i think that might mean that i need a place just to do that... but idk what that should be..."

## The Solution: Zettelkasten + Neo4j + AI Integration

### Core Architecture Vision

> "i was thinking maybe we just write markdown files to github via command that adds them to a folder and force pushes if up-to-date, then all our tagging shows up in neo4j but also shows up as linked markdown inside the github, which automatically makes a wiki that is browseable."

> "we'd have to set it up like a zettelkasten so that it can grow shape organically."

### Technical Implementation

The system consists of:

1. **Markdown Files**: Source of truth for all ideas and concepts
2. **Auto-linking System**: "Basically we have a bunch of files that are markdown with a keyword detector such that any keyword that is also a concept file gets auto-linked. IE every proper mention is auto-linked"
3. **Neo4j Graph**: "the neo4j just reflects the current state of links and file names"
4. **GitHub Integration**: "the github just provides a backup, the neo4j doesnt need to back up because it's only being used for query not for CREATE or MERGE"

### Key Insight: Read-Only Neo4j

> "yeah but does that ever need to write to the graph?"

The architecture is elegantly simple:
- **Markdown files** → Auto-linking detects keywords → **Neo4j** rebuilds graph from current state
- **Neo4j** is purely a computed view, not a database
- **GitHub** provides version control and backup

### Why This Works

> "yeah i think neo4j is better though because u can read locally and view the graph via neo4j thats all it has to be. this will be powerful"

Benefits:
- **Visual thinking**: See idea clusters in Neo4j Browser
- **Local speed**: No API calls, instant queries  
- **Discovery**: Rich relationship queries
- **AI integration**: Claude can query the graph for context
- **Organic growth**: No forced structure, patterns emerge naturally

## The Desired Workflow

1. **Idea Capture**: Write thoughts in markdown files
2. **Auto-linking**: System detects [[concept]] references and links them
3. **Graph Building**: Neo4j reflects current relationship state
4. **Visual Exploration**: Browse idea connections in Neo4j Browser
5. **AI Collaboration**: Chat with Claude about ideas using graph context

As the founder explained:

> "Then, being able to do them is really just a question of dropping into a chat together until we're able to automate them. I think that's my big idea right now... what is the actual architecture we need to make that happen???"

## MCP Implementation Goals

The Idea Concepts MCP will provide:

### Core Tools
- **Sync Operations**: Pull markdown from GitHub, build Neo4j graph
- **Concept Queries**: Find related concepts, discover patterns
- **Graph Navigation**: Traverse relationships, find concept neighbors
- **Content Search**: Search concepts by content, tags, connections
- **Visualization Data**: Export graph data for UI visualization

### Configuration
- **GitHub PAT**: For repository access
- **Neo4j Connection**: URL, credentials for graph database
- **Repository**: Target GitHub repo for markdown files
- **Namespace**: User-specific labels for multi-tenant Neo4j

### Architecture Principles
1. **Read-Only Neo4j**: No complex write operations, just graph rebuilds
2. **Markdown as Truth**: All edits happen in markdown, not through MCP
3. **Auto-Discovery**: Keyword detection creates relationships automatically
4. **Local First**: Works with local Neo4j for speed and privacy
5. **GitHub Backup**: Optional sync for version control and sharing

## The Bigger Vision

This MCP enables the core Meta-Frontend concept:

> "I want that. Then, being able to do them is really just a question of dropping into a chat together until we're able to automate them."

The Idea Concepts MCP becomes the **thinking layer** that bridges:
- **Ideas** (captured in markdown)
- **AI Collaboration** (Claude with full context)
- **Development** (transition from ideas to implementation)

This creates the foundation for **AI-assisted thinking architecture** where users can:
- Capture thoughts naturally
- Visualize idea relationships
- Chat with AI about concepts using rich context
- Smoothly transition from thinking to building

As the founder noted:

> "The local setup means it's fast, private, and you control everything. Perfect!"

---

*This MCP represents a crucial component of the Meta-Frontend vision: enabling augmented thinking through AI collaboration with rich context understanding.*