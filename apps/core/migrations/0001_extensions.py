from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
                CREATE EXTENSION IF NOT EXISTS unaccent;
                CREATE EXTENSION IF NOT EXISTS btree_gin;
                CREATE EXTENSION IF NOT EXISTS btree_gist;
                CREATE EXTENSION IF NOT EXISTS vector;

                CREATE OR REPLACE FUNCTION f_unaccent_lower(text)
                RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
                $$ SELECT lower(unaccent('unaccent', $1)) $$;

                CREATE OR REPLACE FUNCTION trg_set_updated_at()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    NEW.updated_at = now();
                    RETURN NEW;
                END $$;
            """,
            reverse_sql="""
                DROP FUNCTION IF EXISTS trg_set_updated_at();
                DROP FUNCTION IF EXISTS f_unaccent_lower(text);
                DROP EXTENSION IF EXISTS vector;
                DROP EXTENSION IF EXISTS btree_gist;
                DROP EXTENSION IF EXISTS btree_gin;
                DROP EXTENSION IF EXISTS unaccent;
                DROP EXTENSION IF EXISTS pg_trgm;
            """,
        ),
    ]
