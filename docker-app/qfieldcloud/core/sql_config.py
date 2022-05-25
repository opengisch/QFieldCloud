from migrate_sql.config import SQLItem

sql_items = [
    SQLItem(
        "project_user_collaborators_vw",
        """
            CREATE OR REPLACE VIEW project_user_collaborators_vw AS

            SELECT
                C1.*,
                (
                    O1.user_ptr_id IS NULL AND P1.is_public
                    OR OM1.id IS NOT NULL
                ) AS "is_valid"
            FROM
                core_projectcollaborator C1
                INNER JOIN core_project P1 ON P1.id = C1.project_id
                LEFT JOIN core_organization O1 ON O1.user_ptr_id = P1.owner_id
                LEFT JOIN core_organizationmember OM1 ON OM1.organization_id = O1.user_ptr_id
        """,
        """
            DROP VIEW project_user_collaborators_vw;
        """,
    ),
    SQLItem(
        "projects_with_roles_vw",
        """
            CREATE OR REPLACE VIEW projects_with_roles_vw AS

            WITH project_owner AS (
                SELECT
                    P1."id" AS "project_id",
                    P1."owner_id" AS "user_id",
                    'admin' AS "name",
                    'project_owner' AS "origin",
                    TRUE AS "is_valid"
                FROM
                    "core_project" P1
                    INNER JOIN "core_user" U1 ON (P1."owner_id" = U1."id")
                WHERE
                    U1."user_type" = 1
            ),
            organization_owner AS (
                SELECT
                    P1."id" AS "project_id",
                    O1."organization_owner_id" AS "user_id",
                    'admin' AS "name",
                    'organization_owner' AS "origin",
                    TRUE AS "is_valid"
                FROM
                    "core_organization" O1
                    INNER JOIN "core_project" P1 ON (P1."owner_id" = O1."user_ptr_id")
            ),
            organization_admin AS (
                SELECT
                    P1."id" AS "project_id",
                    OM1."member_id" AS "user_id",
                    'admin' AS "name",
                    'organization_admin' AS "origin",
                    TRUE AS "is_valid"
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
                    C1."project_id",
                    C1."collaborator_id" AS "user_id",
                    C1."role" AS "name",
                    'collaborator' AS "origin",
                    P1.is_public OR U1.user_type = 2 AS "is_valid"
                FROM
                    "project_user_collaborators_vw" C1
                    INNER JOIN "core_project" P1 ON (P1."id" = C1."project_id")
                    INNER JOIN "core_user" U1 ON (P1."owner_id" = U1."id")
                WHERE
                    C1."is_valid" = TRUE
            ),
            project_collaborator_team AS (
                SELECT
                    C1."project_id",
                    TM1."member_id" AS "user_id",
                    C1."role" AS "name",
                    'team_member' AS "origin",
                    TRUE AS "is_valid"
                FROM
                    "core_projectcollaborator" C1
                    INNER JOIN "core_user" U1 ON (C1."collaborator_id" = U1."id")
                    INNER JOIN "core_team" T1 ON (U1."id" = T1."user_ptr_id")
                    INNER JOIN "core_teammember" TM1 ON (T1."user_ptr_id" = TM1."team_id")
                    INNER JOIN "core_project" P1 ON (P1."id" = C1."project_id")
            )
            SELECT DISTINCT ON(project_id, user_id)
                row_number() OVER () AS id,
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
            ) AS R1
        """,
        """
            DROP VIEW projects_with_roles_vw;
        """,
        dependencies=["project_user_collaborators_vw"],
    ),
]
