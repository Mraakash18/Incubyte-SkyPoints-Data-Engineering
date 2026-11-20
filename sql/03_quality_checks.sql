-- Run these read-only queries after the Snowflake ETL batch.

-- Mandatory fields (should be zero):
SELECT COUNT(*) AS missing_mandatory
FROM SKYPOINTS.CURRENT_MEMBERS
WHERE member_key IS NULL OR TRIM(member_name)='' OR enrollment_date IS NULL;

-- Canonical key uniqueness (Snowflake standard PKs are not enforced):
SELECT member_key,COUNT(*) AS duplicates
FROM SKYPOINTS.CURRENT_MEMBERS GROUP BY member_key HAVING COUNT(*)>1;

-- Country table duplicates and misplaced rows:
SELECT 'IND' AS table_code,COUNT(*) AS wrong_country
FROM SKYPOINTS.COUNTRY_INDIA WHERE country_code<>'IND'
UNION ALL SELECT 'USA',COUNT(*) FROM SKYPOINTS.COUNTRY_USA WHERE country_code<>'USA'
UNION ALL SELECT 'AUS',COUNT(*) FROM SKYPOINTS.COUNTRY_AUSTRALIA WHERE country_code<>'AUS'
UNION ALL SELECT 'PHL',COUNT(*) FROM SKYPOINTS.COUNTRY_PHILIPPINES WHERE country_code<>'PHL'
UNION ALL SELECT 'CAN',COUNT(*) FROM SKYPOINTS.COUNTRY_CANADA WHERE country_code<>'CAN';

-- Cross-country duplicate membership (should return zero rows):
SELECT member_key,COUNT(*) AS country_copies FROM (
    SELECT member_key FROM SKYPOINTS.COUNTRY_INDIA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_USA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_AUSTRALIA UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_PHILIPPINES UNION ALL
    SELECT member_key FROM SKYPOINTS.COUNTRY_CANADA
) GROUP BY member_key HAVING COUNT(*)<>1;

-- Canonical-to-country count reconciliation (expected equal per country):
WITH country_counts AS (
    SELECT 'IND' AS country_code,COUNT(*) AS target_count FROM SKYPOINTS.COUNTRY_INDIA
    UNION ALL SELECT 'USA',COUNT(*) FROM SKYPOINTS.COUNTRY_USA
    UNION ALL SELECT 'AUS',COUNT(*) FROM SKYPOINTS.COUNTRY_AUSTRALIA
    UNION ALL SELECT 'PHL',COUNT(*) FROM SKYPOINTS.COUNTRY_PHILIPPINES
    UNION ALL SELECT 'CAN',COUNT(*) FROM SKYPOINTS.COUNTRY_CANADA
)
SELECT c.country_code,c.target_count,COUNT(m.member_key) AS canonical_count
FROM country_counts c LEFT JOIN SKYPOINTS.CURRENT_MEMBERS m
ON m.country_code=c.country_code
GROUP BY c.country_code,c.target_count
HAVING c.target_count<>COUNT(m.member_key);

-- Invalid dates/order (should return zero rows):
SELECT member_key,enrollment_date,last_flight_date,dob
FROM SKYPOINTS.CURRENT_MEMBERS
WHERE last_flight_date<enrollment_date OR dob>enrollment_date;

-- Duplicate redemptions (should return zero rows):
SELECT member_key,partner,txn_id,COUNT(*) AS duplicates
FROM SKYPOINTS.REDEMPTION_TRANSACTIONS
GROUP BY member_key,partner,txn_id HAVING COUNT(*)>1;

-- Orphan redemptions: do not discard; investigate/await profile arrival.
SELECT r.member_key,r.txn_id,r.partner
FROM SKYPOINTS.REDEMPTION_TRANSACTIONS r
LEFT JOIN SKYPOINTS.CURRENT_MEMBERS m ON r.member_key=m.member_key
WHERE m.member_key IS NULL;

-- Partner reconciliation of *completed* miles only:
SELECT partner,txn_date,COUNT(*) AS completed_txns,SUM(miles_redeemed) AS completed_miles
FROM SKYPOINTS.REDEMPTION_TRANSACTIONS
WHERE status='COMPLETED'
GROUP BY partner,txn_date ORDER BY partner,txn_date;
