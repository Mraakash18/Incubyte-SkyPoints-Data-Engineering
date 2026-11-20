-- Snowflake reference schema (not executed by the local SQLite demo).
-- Run with a role allowed to create tables in your chosen database.
CREATE SCHEMA IF NOT EXISTS SKYPOINTS;

-- Raw: lossless, immutable record with lineage. Original source fields remain in VARIANT.
CREATE TABLE IF NOT EXISTS SKYPOINTS.RAW_MEMBER_PROFILE (
    raw_id NUMBER IDENTITY, batch_id VARCHAR(100) NOT NULL,
    source_file VARCHAR(500) NOT NULL, source_namespace VARCHAR(50) NOT NULL,
    source_row NUMBER NOT NULL, source_feed_date DATE NOT NULL,
    raw_payload VARIANT NOT NULL, raw_hash VARCHAR(64) NOT NULL,
    ingested_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS SKYPOINTS.RAW_REDEMPTIONS (
    batch_id VARCHAR(100) NOT NULL, source_file VARCHAR(500) NOT NULL,
    raw_payload VARIANT NOT NULL, ingested_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Adapter output: country-specific CSV/XLSX/flat-file schemas standardized to ISO strings.
-- Keep source_updated_at when provided; the assessment samples do not supply one.
CREATE TABLE IF NOT EXISTS SKYPOINTS.NORMALIZED_MEMBER_INPUT (
    batch_id VARCHAR(100) NOT NULL, source_file VARCHAR(500) NOT NULL,
    source_row NUMBER NOT NULL, source_namespace VARCHAR(50) NOT NULL,
    source_member_id VARCHAR(18), member_name VARCHAR(255),
    tier_code VARCHAR(5), enrollment_date_text VARCHAR(10),
    last_flight_date_text VARCHAR(10), dob_text VARCHAR(10),
    country_code VARCHAR(3), member_type VARCHAR(1), is_active VARCHAR(1),
    agent_name VARCHAR(255), state_code VARCHAR(5), post_code VARCHAR(5),
    source_feed_date DATE NOT NULL, source_updated_at TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS SKYPOINTS.STAGING_MEMBERS (
    batch_id VARCHAR(100) NOT NULL,
    member_key VARCHAR(80) NOT NULL, source_member_id VARCHAR(18) NOT NULL,
    source_namespace VARCHAR(50) NOT NULL, member_name VARCHAR(255) NOT NULL,
    tier_code VARCHAR(5), enrollment_date DATE NOT NULL, last_flight_date DATE,
    dob DATE, country_code VARCHAR(3) NOT NULL, member_type VARCHAR(1),
    is_active VARCHAR(1), agent_name VARCHAR(255), state_code VARCHAR(5),
    post_code VARCHAR(5), age NUMBER(3,0), stale_member BOOLEAN,
    as_of_date DATE NOT NULL, source_feed_date DATE NOT NULL,
    source_updated_at TIMESTAMP_NTZ, source_file VARCHAR(500), source_row NUMBER
);

CREATE TABLE IF NOT EXISTS SKYPOINTS.CURRENT_MEMBERS (
    member_key VARCHAR(80) NOT NULL, source_member_id VARCHAR(18) NOT NULL,
    source_namespace VARCHAR(50) NOT NULL, member_name VARCHAR(255) NOT NULL,
    tier_code VARCHAR(5), enrollment_date DATE NOT NULL, last_flight_date DATE,
    dob DATE, country_code VARCHAR(3) NOT NULL, member_type VARCHAR(1),
    is_active VARCHAR(1), agent_name VARCHAR(255), state_code VARCHAR(5),
    post_code VARCHAR(5), age NUMBER(3,0), stale_member BOOLEAN,
    as_of_date DATE NOT NULL, source_feed_date DATE NOT NULL,
    source_updated_at TIMESTAMP_NTZ, source_file VARCHAR(500), source_row NUMBER,
    CONSTRAINT pk_member PRIMARY KEY (member_key)
);

-- Physical country tables requested by the assessment. Add countries through a
-- controlled deployment/migration process; never interpolate untrusted country text.
CREATE TABLE IF NOT EXISTS SKYPOINTS.COUNTRY_INDIA LIKE SKYPOINTS.CURRENT_MEMBERS;
CREATE TABLE IF NOT EXISTS SKYPOINTS.COUNTRY_USA LIKE SKYPOINTS.CURRENT_MEMBERS;
CREATE TABLE IF NOT EXISTS SKYPOINTS.COUNTRY_AUSTRALIA LIKE SKYPOINTS.CURRENT_MEMBERS;
CREATE TABLE IF NOT EXISTS SKYPOINTS.COUNTRY_PHILIPPINES LIKE SKYPOINTS.CURRENT_MEMBERS;
CREATE TABLE IF NOT EXISTS SKYPOINTS.COUNTRY_CANADA LIKE SKYPOINTS.CURRENT_MEMBERS;

CREATE TABLE IF NOT EXISTS SKYPOINTS.REDEMPTION_TRANSACTIONS (
    member_key VARCHAR(80) NOT NULL, source_member_id VARCHAR(18) NOT NULL,
    partner VARCHAR(255) NOT NULL, txn_id VARCHAR(100) NOT NULL,
    txn_date DATE NOT NULL, miles_redeemed NUMBER(18,0) NOT NULL,
    status VARCHAR(20) NOT NULL, feed_date DATE NOT NULL,
    CONSTRAINT pk_redemption PRIMARY KEY (member_key, partner, txn_id)
);

CREATE TABLE IF NOT EXISTS SKYPOINTS.REJECTED_RECORDS (
    batch_id VARCHAR(100), source_file VARCHAR(500), source_row NUMBER,
    reason VARCHAR(500) NOT NULL, raw_payload VARIANT,
    rejected_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- IMPORTANT: Snowflake standard-table PRIMARY KEY constraints are informational,
-- not enforced. Enforce deduplication in transformations and data-quality checks.
