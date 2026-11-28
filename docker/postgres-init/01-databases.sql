-- Local development only: one database per service on the shared Postgres container.
CREATE DATABASE review_desk OWNER govhub;
CREATE DATABASE assessment_engine OWNER govhub;
CREATE DATABASE control_centre OWNER govhub;
-- The services run as govhub_app: owns nothing, cannot bypass row-level security.
-- Migrations run as govhub (the owner) and grant it table rights. Local dev password only.
CREATE ROLE govhub_app LOGIN PASSWORD 'govhub_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
