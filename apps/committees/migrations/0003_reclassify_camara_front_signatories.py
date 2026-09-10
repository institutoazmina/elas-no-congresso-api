from django.db import migrations

RECLASSIFY_CAMARA_FRONT_SIGNATORIES = """
WITH ranked AS (
    SELECT
        cm.id,
        ROW_NUMBER() OVER (
            PARTITION BY cm.caucus_id, cm.parliamentarian_id
            ORDER BY
                CASE
                    WHEN cm.source_key LIKE c.source_key || ':member:%' THEN 0
                    ELSE 1
                END,
                cm.id
        ) AS duplicate_rank
    FROM caucus_memberships cm
    JOIN caucuses c ON c.id = cm.caucus_id
    WHERE cm.source = 'camara' AND c.kind = 'frente'
)
DELETE FROM caucus_memberships
WHERE id IN (
    SELECT id FROM ranked WHERE duplicate_rank > 1
);

UPDATE caucus_memberships cm
SET
    source_key = CASE
        WHEN cm.source_key LIKE '%:member:%'
        THEN c.source_key || substring(cm.source_key FROM ':member:.*$')
        ELSE cm.source_key
    END,
    role = 'Signatário',
    start_date = NULL,
    end_date = NULL,
    is_observed_current = NULL
FROM caucuses c
WHERE
    c.id = cm.caucus_id
    AND cm.source = 'camara'
    AND c.kind = 'frente';
"""


class Migration(migrations.Migration):
    dependencies = [("committees", "0002_provenance_and_date_ranges")]

    operations = [
        migrations.RunSQL(
            RECLASSIFY_CAMARA_FRONT_SIGNATORIES,
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
