-- Local development only: one database per service on the shared Postgres container.
CREATE DATABASE review_desk OWNER govhub;
CREATE DATABASE assessment_engine OWNER govhub;
CREATE DATABASE control_centre OWNER govhub;
