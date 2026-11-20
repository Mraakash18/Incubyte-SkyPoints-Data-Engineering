-- Illustrative Snowflake batch transformation, assuming source adapters have loaded
-- NORMALIZED_MEMBER_INPUT with ISO YYYY-MM-DD strings and normalized country codes.
-- Review and configure these variables for each batch.
SET BATCH_ID = '20240115_sample';
SET AS_OF_DATE = '2026-11-20';

-- 1. Quarantine invalid dates and missing required values before staging.
INSERT INTO SKYPOINTS.REJECTED_RECORDS (batch_id,source_file,source_row,reason,raw_payload)
SELECT batch_id, source_file, source_row,
       CASE
         WHEN TRIM(COALESCE(source_member_id,'')) = '' THEN 'MISSING_MEMBER_ID'
         WHEN TRIM(COALESCE(member_name,'')) = '' THEN 'MISSING_MEMBER_NAME'
         WHEN TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD') IS NULL THEN 'INVALID_ENROLLMENT_DATE'
         WHEN last_flight_date_text IS NOT NULL AND
              TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') IS NULL THEN 'INVALID_FLIGHT_DATE'
         WHEN dob_text IS NOT NULL AND TRY_TO_DATE(dob_text,'YYYY-MM-DD') IS NULL THEN 'INVALID_DOB'
         WHEN country_code NOT IN ('IND','USA','AUS','PHL','CAN') OR country_code IS NULL THEN 'UNKNOWN_COUNTRY'
         WHEN tier_code IS NOT NULL AND tier_code NOT IN ('SLV','GLD','PLT') THEN 'UNKNOWN_TIER'
         WHEN member_type IS NOT NULL AND member_type NOT IN ('I','C') THEN 'INVALID_MEMBER_TYPE'
         WHEN is_active IS NOT NULL AND is_active NOT IN ('A','I') THEN 'INVALID_ACTIVE_FLAG'
         WHEN TRY_TO_DATE(dob_text,'YYYY-MM-DD') > TO_DATE($AS_OF_DATE) THEN 'DOB_IN_FUTURE'
         ELSE 'INVALID_DATE_ORDER'
       END,
       OBJECT_CONSTRUCT_KEEP_NULL(*)
FROM SKYPOINTS.NORMALIZED_MEMBER_INPUT
WHERE batch_id = $BATCH_ID AND (
    TRIM(COALESCE(source_member_id,'')) = '' OR
    TRIM(COALESCE(member_name,'')) = '' OR
    TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD') IS NULL OR
    (last_flight_date_text IS NOT NULL AND TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') IS NULL) OR
    (dob_text IS NOT NULL AND TRY_TO_DATE(dob_text,'YYYY-MM-DD') IS NULL) OR
    (country_code NOT IN ('IND','USA','AUS','PHL','CAN') OR country_code IS NULL) OR
    (tier_code IS NOT NULL AND tier_code NOT IN ('SLV','GLD','PLT')) OR
    (member_type IS NOT NULL AND member_type NOT IN ('I','C')) OR
    (is_active IS NOT NULL AND is_active NOT IN ('A','I')) OR
    TRY_TO_DATE(dob_text,'YYYY-MM-DD') > TO_DATE($AS_OF_DATE) OR
    TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') < TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD') OR
    TRY_TO_DATE(dob_text,'YYYY-MM-DD') > TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD') OR
    TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') > TO_DATE($AS_OF_DATE)
);

-- 2. Validated staging, including age and stale-member derivations.
INSERT INTO SKYPOINTS.STAGING_MEMBERS (
    batch_id,member_key,source_member_id,source_namespace,member_name,tier_code,
    enrollment_date,last_flight_date,dob,country_code,member_type,is_active,
    agent_name,state_code,post_code,age,stale_member,as_of_date,
    source_feed_date,source_updated_at,source_file,source_row
)
SELECT batch_id, source_namespace || ':' || source_member_id,
       source_member_id,source_namespace,member_name,tier_code,
       TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD'),
       TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD'),
       TRY_TO_DATE(dob_text,'YYYY-MM-DD'),country_code,member_type,is_active,
       agent_name,state_code,post_code,
       CASE WHEN TRY_TO_DATE(dob_text,'YYYY-MM-DD') IS NULL THEN NULL ELSE
         DATEDIFF('year',TRY_TO_DATE(dob_text,'YYYY-MM-DD'),TO_DATE($AS_OF_DATE))
         - IFF(TO_CHAR(TRY_TO_DATE(dob_text,'YYYY-MM-DD'),'MMDD') >
               TO_CHAR(TO_DATE($AS_OF_DATE),'MMDD'),1,0) END,
       CASE WHEN TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') IS NULL THEN NULL
            ELSE DATEDIFF('day',TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD'),
                          TO_DATE($AS_OF_DATE)) > 90 END,
       TO_DATE($AS_OF_DATE),source_feed_date,source_updated_at,source_file,source_row
FROM SKYPOINTS.NORMALIZED_MEMBER_INPUT
WHERE batch_id = $BATCH_ID AND
      TRIM(COALESCE(source_member_id,'')) <> '' AND
      TRIM(COALESCE(member_name,'')) <> '' AND
      TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD') IS NOT NULL AND
      (last_flight_date_text IS NULL OR TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') IS NOT NULL) AND
      (dob_text IS NULL OR TRY_TO_DATE(dob_text,'YYYY-MM-DD') IS NOT NULL) AND
      country_code IN ('IND','USA','AUS','PHL','CAN') AND
      (tier_code IS NULL OR tier_code IN ('SLV','GLD','PLT')) AND
      (member_type IS NULL OR member_type IN ('I','C')) AND
      (is_active IS NULL OR is_active IN ('A','I')) AND
      (dob_text IS NULL OR TRY_TO_DATE(dob_text,'YYYY-MM-DD') <= TO_DATE($AS_OF_DATE)) AND
      (last_flight_date_text IS NULL OR TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') >=
                                             TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD')) AND
      (dob_text IS NULL OR TRY_TO_DATE(dob_text,'YYYY-MM-DD') <=
                                 TRY_TO_DATE(enrollment_date_text,'YYYY-MM-DD')) AND
      (last_flight_date_text IS NULL OR TRY_TO_DATE(last_flight_date_text,'YYYY-MM-DD') <= TO_DATE($AS_OF_DATE));

-- 3. Identify same-date contradictory records. Do not arbitrarily choose one.
CREATE OR REPLACE TEMP TABLE SKYPOINTS.BATCH_CONFLICTS AS
SELECT member_key,source_feed_date
FROM SKYPOINTS.STAGING_MEMBERS
WHERE batch_id = $BATCH_ID
GROUP BY member_key,source_feed_date
HAVING COUNT(DISTINCT HASH(member_name,country_code,tier_code,enrollment_date,
                           last_flight_date,dob,member_type,is_active)) > 1;

INSERT INTO SKYPOINTS.REJECTED_RECORDS (batch_id,source_file,source_row,reason,raw_payload)
SELECT s.batch_id,s.source_file,s.source_row,'CONFLICTING_SAME_FEED_DATE',
       OBJECT_CONSTRUCT_KEEP_NULL('member_key',s.member_key,'country_code',s.country_code)
FROM SKYPOINTS.STAGING_MEMBERS s
JOIN SKYPOINTS.BATCH_CONFLICTS c
  ON s.member_key=c.member_key AND s.source_feed_date=c.source_feed_date
WHERE s.batch_id = $BATCH_ID;

-- 4. Pick the latest unambiguous version for each member in the batch.
-- A genuine source_updated_at is preferable; feed_date is only a fallback.
CREATE OR REPLACE TEMP TABLE SKYPOINTS.BATCH_WINNERS AS
SELECT s.*
FROM SKYPOINTS.STAGING_MEMBERS s
WHERE s.batch_id = $BATCH_ID AND NOT EXISTS (
    SELECT 1 FROM SKYPOINTS.BATCH_CONFLICTS c
    WHERE c.member_key=s.member_key AND c.source_feed_date=s.source_feed_date
)
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY s.member_key
    ORDER BY COALESCE(s.source_updated_at,s.source_feed_date::TIMESTAMP_NTZ) DESC,
             s.source_feed_date DESC,s.source_file DESC,s.source_row DESC
)=1;

-- 5. Prepare only new/newer changes, not full historical reprocessing.
CREATE OR REPLACE TEMP TABLE SKYPOINTS.BATCH_CHANGES AS
SELECT b.member_key,b.source_member_id,b.source_namespace,b.member_name,b.tier_code,
       b.enrollment_date,b.last_flight_date,b.dob,b.country_code,b.member_type,
       b.is_active,b.agent_name,b.state_code,b.post_code,b.age,b.stale_member,
       b.as_of_date,b.source_feed_date,b.source_updated_at,b.source_file,b.source_row
FROM SKYPOINTS.BATCH_WINNERS b
LEFT JOIN SKYPOINTS.CURRENT_MEMBERS c ON c.member_key=b.member_key
WHERE c.member_key IS NULL OR
      COALESCE(b.source_updated_at,b.source_feed_date::TIMESTAMP_NTZ) >
      COALESCE(c.source_updated_at,c.source_feed_date::TIMESTAMP_NTZ);

-- 6. Atomic move: remove outdated country membership, upsert canonical and target.
BEGIN TRANSACTION;
DELETE FROM SKYPOINTS.COUNTRY_INDIA
 WHERE member_key IN (SELECT member_key FROM SKYPOINTS.BATCH_CHANGES WHERE country_code <> 'IND');
DELETE FROM SKYPOINTS.COUNTRY_USA
 WHERE member_key IN (SELECT member_key FROM SKYPOINTS.BATCH_CHANGES WHERE country_code <> 'USA');
DELETE FROM SKYPOINTS.COUNTRY_AUSTRALIA
 WHERE member_key IN (SELECT member_key FROM SKYPOINTS.BATCH_CHANGES WHERE country_code <> 'AUS');
DELETE FROM SKYPOINTS.COUNTRY_PHILIPPINES
 WHERE member_key IN (SELECT member_key FROM SKYPOINTS.BATCH_CHANGES WHERE country_code <> 'PHL');
DELETE FROM SKYPOINTS.COUNTRY_CANADA
 WHERE member_key IN (SELECT member_key FROM SKYPOINTS.BATCH_CHANGES WHERE country_code <> 'CAN');

MERGE INTO SKYPOINTS.CURRENT_MEMBERS t USING SKYPOINTS.BATCH_CHANGES s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;

MERGE INTO SKYPOINTS.COUNTRY_INDIA t
USING (SELECT * FROM SKYPOINTS.BATCH_CHANGES WHERE country_code='IND') s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;
MERGE INTO SKYPOINTS.COUNTRY_USA t
USING (SELECT * FROM SKYPOINTS.BATCH_CHANGES WHERE country_code='USA') s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;
MERGE INTO SKYPOINTS.COUNTRY_AUSTRALIA t
USING (SELECT * FROM SKYPOINTS.BATCH_CHANGES WHERE country_code='AUS') s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;
MERGE INTO SKYPOINTS.COUNTRY_PHILIPPINES t
USING (SELECT * FROM SKYPOINTS.BATCH_CHANGES WHERE country_code='PHL') s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;
MERGE INTO SKYPOINTS.COUNTRY_CANADA t
USING (SELECT * FROM SKYPOINTS.BATCH_CHANGES WHERE country_code='CAN') s
ON t.member_key=s.member_key
WHEN MATCHED THEN UPDATE ALL BY NAME
WHEN NOT MATCHED THEN INSERT ALL BY NAME;
COMMIT;

-- 7. Flatten semi-structured JSON redemptions. Raw payload shape:
-- {"member_id":"223457","feed_date":"20240115","redemptions":[{...}]}
CREATE OR REPLACE TEMP TABLE SKYPOINTS.FLATTENED_REDEMPTIONS AS
SELECT r.source_file, f.index AS source_row,
       'GLOBAL:' || COALESCE(r.raw_payload:member_id::STRING,'') AS member_key,
       r.raw_payload:member_id::STRING AS source_member_id,
       f.value:partner::STRING AS partner,
       f.value:txn_id::STRING AS txn_id,
       TRY_TO_DATE(f.value:txn_date::STRING,'YYYYMMDD') AS txn_date,
       TRY_TO_NUMBER(f.value:miles_redeemed::STRING) AS miles_redeemed,
       UPPER(f.value:status::STRING) AS status,
       TRY_TO_DATE(r.raw_payload:feed_date::STRING,'YYYYMMDD') AS feed_date,
       f.value AS raw_transaction
FROM SKYPOINTS.RAW_REDEMPTIONS r,
LATERAL FLATTEN(INPUT => r.raw_payload:redemptions) f
WHERE r.batch_id = $BATCH_ID;

-- Detect conflicting versions with the same transaction key and feed date.
CREATE OR REPLACE TEMP TABLE SKYPOINTS.REDEMPTION_CONFLICTS AS
SELECT member_key,partner,txn_id,feed_date
FROM SKYPOINTS.FLATTENED_REDEMPTIONS
WHERE member_key <> 'GLOBAL:' AND partner IS NOT NULL AND txn_id IS NOT NULL
GROUP BY member_key,partner,txn_id,feed_date
HAVING COUNT(DISTINCT HASH(txn_date,miles_redeemed,status)) > 1;

INSERT INTO SKYPOINTS.REJECTED_RECORDS (batch_id,source_file,source_row,reason,raw_payload)
SELECT $BATCH_ID,f.source_file,f.source_row,
       CASE
         WHEN c.member_key IS NOT NULL THEN 'CONFLICTING_REDEMPTION_SAME_FEED_DATE'
         WHEN f.member_key = 'GLOBAL:' THEN 'MISSING_MEMBER_ID'
         WHEN f.partner IS NULL OR f.txn_id IS NULL THEN 'MISSING_TRANSACTION_KEY'
         WHEN f.txn_date IS NULL OR f.feed_date IS NULL OR f.txn_date>f.feed_date THEN 'INVALID_TRANSACTION_DATE'
         WHEN f.miles_redeemed IS NULL OR f.miles_redeemed<=0 OR
              f.miles_redeemed<>FLOOR(f.miles_redeemed) THEN 'INVALID_MILES'
         ELSE 'INVALID_STATUS'
       END,
       f.raw_transaction
FROM SKYPOINTS.FLATTENED_REDEMPTIONS f
LEFT JOIN SKYPOINTS.REDEMPTION_CONFLICTS c
  ON f.member_key=c.member_key AND f.partner=c.partner AND
     f.txn_id=c.txn_id AND f.feed_date=c.feed_date
WHERE c.member_key IS NOT NULL OR f.member_key='GLOBAL:' OR
      f.partner IS NULL OR f.txn_id IS NULL OR
      f.txn_date IS NULL OR f.feed_date IS NULL OR f.txn_date>f.feed_date OR
      f.miles_redeemed IS NULL OR f.miles_redeemed<=0 OR
      f.miles_redeemed<>FLOOR(f.miles_redeemed) OR
      f.status NOT IN ('COMPLETED','PENDING','CANCELLED','FAILED') OR f.status IS NULL;

CREATE OR REPLACE TEMP TABLE SKYPOINTS.VALID_REDEMPTIONS AS
SELECT f.member_key,f.source_member_id,f.partner,f.txn_id,f.txn_date,
       f.miles_redeemed,f.status,f.feed_date
FROM SKYPOINTS.FLATTENED_REDEMPTIONS f
WHERE f.member_key<>'GLOBAL:' AND f.partner IS NOT NULL AND f.txn_id IS NOT NULL
  AND f.txn_date IS NOT NULL AND f.feed_date IS NOT NULL AND f.txn_date<=f.feed_date
  AND f.miles_redeemed>0 AND f.miles_redeemed=FLOOR(f.miles_redeemed)
  AND f.status IN ('COMPLETED','PENDING','CANCELLED','FAILED')
  AND NOT EXISTS (
      SELECT 1 FROM SKYPOINTS.REDEMPTION_CONFLICTS c
      WHERE c.member_key=f.member_key AND c.partner=f.partner AND
            c.txn_id=f.txn_id AND c.feed_date=f.feed_date
  )
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY f.member_key,f.partner,f.txn_id ORDER BY f.feed_date DESC
)=1;

MERGE INTO SKYPOINTS.REDEMPTION_TRANSACTIONS t
USING SKYPOINTS.VALID_REDEMPTIONS s
ON t.member_key=s.member_key AND t.partner=s.partner AND t.txn_id=s.txn_id
WHEN MATCHED AND s.feed_date > t.feed_date THEN
    UPDATE SET t.txn_date=s.txn_date,t.miles_redeemed=s.miles_redeemed,
               t.status=s.status,t.feed_date=s.feed_date
WHEN NOT MATCHED THEN
    INSERT (member_key,source_member_id,partner,txn_id,txn_date,miles_redeemed,status,feed_date)
    VALUES (s.member_key,s.source_member_id,s.partner,s.txn_id,s.txn_date,
            s.miles_redeemed,s.status,s.feed_date);

-- 8. Link verified global member IDs; unmatched redemptions remain visible.
SELECT r.txn_id,r.partner,r.miles_redeemed,r.status,
       m.member_name,m.country_code,m.tier_code,
       IFF(m.member_key IS NULL,'UNMATCHED','MATCHED') AS join_status
FROM SKYPOINTS.REDEMPTION_TRANSACTIONS r
LEFT JOIN SKYPOINTS.CURRENT_MEMBERS m ON r.member_key=m.member_key;

-- Data quality / reconciliation queries:
SELECT country_code,COUNT(*) AS canonical_count
FROM SKYPOINTS.CURRENT_MEMBERS GROUP BY country_code ORDER BY country_code;
SELECT member_key,COUNT(*) AS copies FROM (
    SELECT member_key FROM SKYPOINTS.COUNTRY_INDIA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_USA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_AUSTRALIA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_PHILIPPINES UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_CANADA
) GROUP BY member_key HAVING COUNT(*) > 1;
