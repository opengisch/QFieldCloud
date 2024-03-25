from migrate_sql.config import SQLItem

sql_items = [
    SQLItem(
        "projects_with_roles_vw_seq",
        r"""
            CREATE SEQUENCE IF NOT EXISTS projects_with_roles_vw_seq CACHE 5000 CYCLE
        """,
        r"""
            DROP SEQUENCE IF EXISTS projects_with_roles_vw_seq
        """,
    ),
    SQLItem(
        "projects_with_roles_vw",
        r"""
            CREATE OR REPLACE VIEW projects_with_roles_vw AS

            WITH project_owner AS (
                SELECT
                    1 AS rank,
                    P1."id" AS "project_id",
                    P1."owner_id" AS "user_id",
                    'admin' AS "name",
                    FALSE AS "is_incognito",
                    'project_owner' AS "origin"
                FROM
                    "core_project" P1
                    INNER JOIN "core_user" U1 ON (P1."owner_id" = U1."id")
                WHERE
                    U1."type" = 1
            ),
            organization_owner AS (
                SELECT
                    2 AS rank,
                    P1."id" AS "project_id",
                    O1."organization_owner_id" AS "user_id",
                    'admin' AS "name",
                    FALSE AS "is_incognito",
                    'organization_owner' AS "origin"
                FROM
                    "core_organization" O1
                    INNER JOIN "core_project" P1 ON (P1."owner_id" = O1."user_ptr_id")
            ),
            organization_admin AS (
                SELECT
                    3 AS rank,
                    P1."id" AS "project_id",
                    OM1."member_id" AS "user_id",
                    'admin' AS "name",
                    FALSE AS "is_incognito",
                    'organization_admin' AS "origin"
                FROM
                    "core_organizationmember" OM1
                    INNER JOIN "core_project" P1 ON (P1."owner_id" = OM1."organization_id")
                WHERE
                    (
                        OM1."role" = 'admin'
                    )
            ),
            project_collaborator AS (
                SELECT
                    4 AS rank,
                    C1."project_id",
                    C1."collaborator_id" AS "user_id",
                    C1."role" AS "name",
                    C1."is_incognito" AS "is_incognito",
                    'collaborator' AS "origin"
                FROM
                    "core_projectcollaborator" C1
                    INNER JOIN "core_project" P1 ON (P1."id" = C1."project_id")
                    INNER JOIN "core_user" U1 ON (P1."owner_id" = U1."id")
            ),
            project_collaborator_team AS (
                SELECT
                    5 AS rank,
                    C1."project_id",
                    TM1."member_id" AS "user_id",
                    C1."role" AS "name",
                    C1."is_incognito" AS "is_incognito",
                    'team_member' AS "origin"
                FROM
                    "core_projectcollaborator" C1
                    INNER JOIN "core_user" U1 ON (C1."collaborator_id" = U1."id")
                    INNER JOIN "core_team" T1 ON (U1."id" = T1."user_ptr_id")
                    INNER JOIN "core_teammember" TM1 ON (T1."user_ptr_id" = TM1."team_id")
                    INNER JOIN "core_project" P1 ON (P1."id" = C1."project_id")
            ),
            public_project AS (
                SELECT
                    6 AS rank,
                    P1."id" AS "project_id",
                    U1."id" AS "user_id",
                    'reader' AS "name",
                    FALSE AS "is_incognito",
                    'public' AS "origin"
                FROM
                    "core_project" P1
                    CROSS JOIN "core_user" U1
                WHERE
                    is_public = TRUE
            )
            SELECT DISTINCT ON(project_id, user_id)
                nextval('projects_with_roles_vw_seq') id,
                R1.*
            FROM (
                SELECT * FROM project_owner
                UNION
                SELECT * FROM organization_owner
                UNION
                SELECT * FROM organization_admin
                UNION
                SELECT * FROM project_collaborator
                UNION
                SELECT * FROM project_collaborator_team
                UNION
                SELECT * FROM public_project
            ) R1
            ORDER BY project_id, user_id, rank
        """,
        r"""
            DROP VIEW projects_with_roles_vw;
        """,
    ),
    SQLItem(
        "organizations_with_roles_vw_seq",
        r"""
            CREATE SEQUENCE IF NOT EXISTS organizations_with_roles_vw_seq CACHE 5000 CYCLE
        """,
        r"""
            DROP SEQUENCE IF EXISTS organizations_with_roles_vw_seq
        """,
    ),
    SQLItem(
        "organizations_with_roles_vw",
        r"""
            CREATE OR REPLACE VIEW organizations_with_roles_vw AS
            WITH organization_owner AS (
                SELECT
                    1 AS rank,
                    ORG1."user_ptr_id" AS "organization_id",
                    ORG1."organization_owner_id" AS "user_id",
                    'admin' AS "name",
                    'organization_owner' AS "origin",
                    TRUE AS "is_public"
                FROM
                    "core_organization" ORG1
            ),
            organization_member AS (
                SELECT
                    2 AS rank,
                    M1."organization_id" AS "organization_id",
                    M1."member_id" AS "user_id",
                    M1.role AS "name",
                    'organization_member' AS "origin",
                    M1."is_public" AS "is_public"
                FROM
                    "core_organizationmember" M1
            )
            SELECT DISTINCT ON(organization_id, user_id)
                nextval('organizations_with_roles_vw_seq') id,
                R1.*
            FROM (
                SELECT * FROM organization_owner
                UNION
                SELECT * FROM organization_member
            ) R1
            ORDER BY organization_id, user_id, rank
        """,
        r"""
            DROP VIEW IF EXISTS "organizations_with_roles_vw";
        """,
    ),
    SQLItem(
        "core_delta_geom_trigger_func",
        r"""
            CREATE OR REPLACE FUNCTION core_delta_geom_trigger_func()
            RETURNS trigger
            AS
            $$
                DECLARE
                    delta_srid int;
                    old_geom_wkt text;
                    new_geom_wkt text;
                BEGIN
                    SELECT CASE
                        WHEN jsonb_extract_path_text(NEW.content, 'localLayerCrs') ~ '^EPSG:\d{1,10}$'
                        THEN
                            REGEXP_REPLACE(jsonb_extract_path_text(NEW.content, 'localLayerCrs'), '\D*', '', 'g')::int
                        ELSE
                            NULL
                        END INTO delta_srid;

                    old_geom_wkt := NULLIF( TRIM( jsonb_extract_path_text(NEW.content, 'old', 'geometry') ), '');
                    new_geom_wkt := NULLIF( TRIM( jsonb_extract_path_text(NEW.content, 'new', 'geometry') ), '');

                    IF delta_srid IS NOT NULL
                        AND EXISTS(
                            SELECT *
                            FROM spatial_ref_sys
                            WHERE auth_name = 'EPSG'
                                AND auth_srid = delta_srid
                        )
                    THEN
                        NEW.old_geom := ST_Transform( ST_SetSRID( ST_Force2D( ST_GeomFromText( REPLACE( old_geom_wkt, 'nan', '0' ) ) ), delta_srid ), 4326 );
                        NEW.new_geom := ST_Transform( ST_SetSRID( ST_Force2D( ST_GeomFromText( REPLACE( new_geom_wkt, 'nan', '0' ) ) ), delta_srid ), 4326 );
                    ELSE
                        NEW.old_geom := NULL;
                        NEW.new_geom := NULL;
                    END IF;

                    IF ST_GeometryType(NEW.old_geom) IN ('ST_CircularString', 'ST_CompoundCurve', 'ST_CurvePolygon', 'ST_MultiCurve', 'ST_MultiSurface')
                    THEN
                        NEW.old_geom := ST_CurveToLine(NEW.old_geom);
                    END IF;

                    IF ST_GeometryType(NEW.new_geom) IN ('ST_CircularString', 'ST_CompoundCurve', 'ST_CurvePolygon', 'ST_MultiCurve', 'ST_MultiSurface')
                    THEN
                        NEW.new_geom := ST_CurveToLine(NEW.new_geom);
                    END IF;

                    RETURN NEW;
                END;
            $$
            LANGUAGE PLPGSQL
        """,
        r"""
            DROP FUNCTION IF EXISTS core_delta_geom_trigger_func()
        """,
    ),
    SQLItem(
        "core_delta_geom_update_trigger",
        r"""
            CREATE TRIGGER core_delta_geom_update_trigger BEFORE UPDATE ON core_delta
            FOR EACH ROW
            WHEN (OLD.content IS DISTINCT FROM NEW.content)
            EXECUTE FUNCTION core_delta_geom_trigger_func()
        """,
        r"""
            DROP TRIGGER IF EXISTS core_delta_geom_update_trigger ON core_delta
        """,
    ),
    SQLItem(
        "core_delta_geom_insert_trigger",
        r"""
            CREATE TRIGGER core_delta_geom_insert_trigger BEFORE INSERT ON core_delta
            FOR EACH ROW
            EXECUTE FUNCTION core_delta_geom_trigger_func()
        """,
        r"""
            DROP TRIGGER IF EXISTS core_delta_geom_insert_trigger ON core_delta
        """,
    ),
    SQLItem(
        "core_user_email_partial_uniq",
        r"""
            CREATE UNIQUE INDEX IF NOT EXISTS core_user_email_partial_uniq ON core_user (UPPER(email))
            WHERE type = 1 AND email IS NOT NULL AND email != ''
        """,
        r"""
            DROP INDEX IF EXISTS core_user_email_partial_uniq
        """,
    ),
]
