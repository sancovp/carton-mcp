| feature | sequence |
|---|---|
| Universal_Write | add_concept_tool.py · carton_api.py |
| Soma_Validate | add_concept_tool.py · Soma_Verdict |
| Store_Parity_Obs | add_concept_tool.py · ../../base/soma-prolog/soma_prolog/core.py |
| Queue_Drain | observation_worker_daemon.py · /tmp/heaven_data/carton_queue/ · test_universal_write.py |
| Property_Apply | observation_worker_daemon.py · carton_utils.py |
| Release_Effect_Dispatch | observation_worker_daemon.py · substrate_projector.py |
| Diary_Projection_Handler | substrate_projector.py · Starlog_Boundary · Carton_Write |
| Giint_Registry_Projection | substrate_projector.py |
| State_Machine_Projection | substrate_projector.py · sm_gate.py |
| Ec_Button_Projection | substrate_projector.py · ../../base/soma-prolog/gnosys-vault/gnosys_vault/ec_button.py · /tmp/heaven_data/skills/ · ~/.claude/skills/ |
| Ec_Favorites_Projection | substrate_projector.py · /tmp/heaven_data/dragonbones_favorites/ |
| Uco_Skillchain_Projection | substrate_projector.py · ../../base/chaincompiler/packages/skillchain-compiler/skillchain.py |
| Memory_Tier_Compile | substrate_projector.py · ontology_graphs.py · ~/.claude/projects/-home-GOD/memory/MEMORY.md |
| Graph_Facade | carton_utils.py |
| Retrieval_State_Machines | sm_gate.py |
| Chroma_Lane | chroma_daemon.py · chroma_client.py · smart_chroma_rag.py |
| Exhaust_Records | exhaust_records.py · Record_Types |
| Path_Guard | carton_pathguard.py · substrate_projector.py · server_fastmcp.py · observation_worker_daemon.py · test_carton_pathguard.py · .claude/rules/carton-pathguard.md |
| Observation_Validation | add_concept_tool.py · observation_worker_daemon.py · server_fastmcp.py · test_observation_validation_deadletter.py · .claude/rules/observation-validation-deadletter.md |
| Dead_Letter_Lane | carton_deadletter.py · observation_worker_daemon.py · server_fastmcp.py · test_carton_deadletter.py |
| Worker_Control | carton_worker_control.py · server_fastmcp.py · observation_worker_daemon.py · test_carton_worker_control.py · .claude/rules/daemon-needs-env-vars.md |
| Carton_Write | Universal_Write · Soma_Validate · Queue_Drain · Property_Apply · Graph_Facade · Path_Guard · Observation_Validation · Dead_Letter_Lane |
| Carton_Projection | Release_Effect_Dispatch · Diary_Projection_Handler · Giint_Registry_Projection · State_Machine_Projection · Ec_Button_Projection · Ec_Favorites_Projection · Uco_Skillchain_Projection · Memory_Tier_Compile |
| Carton_Boundary | Carton_Write · Carton_Projection · Retrieval_State_Machines · Chroma_Lane · Exhaust_Records · Store_Parity_Obs · Soma_Verdict · Vault_Boundary |
