# carton_store

## THE GRAPH IS SAVED AND EXPORTED ON A CRON
The neo4j Wiki graph is saved and exported on a cron.
The live graph is backed up to a host-resident path through an online lane, its consistency stated,
before any carton-saas config change or GNOSYS e2e run.

## ONE NAME, ONE NODE
The hyphen and underscore shadow-twin pairs collapse to one node each. Removing a relationship resolves a
name exactly as adding one does, so no new twin forms, and the dedupe tool sees every pair.
The legacy has_actual_domain edges are copied to has_domain, probed first.
