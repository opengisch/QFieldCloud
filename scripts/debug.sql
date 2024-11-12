-- \i ./scripts/debug.sql

DROP VIEW IF EXISTS debug_users_slim_vw;
DROP VIEW IF EXISTS debug_users_vw;
DROP VIEW IF EXISTS debug_projects_slim_vw;
DROP VIEW IF EXISTS debug_projects_vw;
DROP VIEW IF EXISTS debug_deltas_slim_vw;
DROP VIEW IF EXISTS debug_deltas_vw;
DROP VIEW IF EXISTS debug_jobs_slim_vw;
DROP VIEW IF EXISTS debug_jobs_vw;


CREATE OR REPLACE TEMPORARY VIEW debug_users_vw AS
    SELECT
        U.id AS user_id,
        LOWER(U.username) AS username,
        LOWER(U.email) AS email,
        U.first_name,
        U.last_name,
        U.is_staff,
        U.is_active,
        U.last_login,
        U.date_joined,
        U.type,
        -- U.has_accepted_tos,
        -- U.has_newsletter_subscription,
        -- UAT.code AS project_owner_plan,

        COALESCE(P.projects_count, 0) AS projects_count,
        COALESCE(O.organizations_count, 0) AS organizations_count,
        jsonb_pretty(P.projects) AS projects,
        jsonb_pretty(O.organizations) AS organizations
    FROM
        core_user U
        JOIN core_useraccount UA ON UA.user_id = U.id
        -- JOIN subscription_plan UAT ON UAT.id = UA.plan_id
        LEFT JOIN (
            SELECT
                user_id,
                COUNT(P1) FILTER (WHERE is_public = FALSE) AS projects_count,
                jsonb_agg(P1) AS projects
            FROM (
                    SELECT
                        P2.name,
                        P2.created_at,
                        P2.id AS project_id,
                        U1.username AS project_owner_username,
                        P2.owner_id AS project_owner_id,
                        P2.is_public,
                        PR.user_id,
                        PR.name AS role,
                        PR.origin AS role_origin
                    FROM
                        core_project P2
                    JOIN core_user U1 ON U1.id = P2.owner_id
                    LEFT JOIN projects_with_roles_vw PR ON PR.project_id = P2.id
                    WHERE PR.origin != 'public'

            ) P1
            GROUP BY user_id
        ) P ON P.user_id = U.id
        LEFT JOIN (
            SELECT
                user_id,
                COUNT(O2) AS organizations_count,
                jsonb_agg(O2) AS organizations
            FROM (
                    SELECT
                        U1.username AS name,
                        O2.user_ptr_id AS organization_id,
                        U2.username AS organization_owner_username,
                        O2.organization_owner_id AS organization_owner_id,
                        ORGR.user_id,
                        ORGR.name AS role,
                        ORGR.origin AS role_origin
                    FROM
                        core_organization O2
                    JOIN core_user U1 ON U1.id = O2.user_ptr_id
                    JOIN core_user U2 ON U2.id = O2.organization_owner_id
                    LEFT JOIN organizations_with_roles_vw ORGR ON ORGR.organization_id = O2.user_ptr_id

            ) O2
            GROUP BY user_id
        ) O ON O.user_id = U.id
;


CREATE OR REPLACE TEMPORARY VIEW debug_users_slim_vw AS
    SELECT
        user_id,
        username,
        email,
        first_name,
        last_name,
        is_staff,
        is_active,
        last_login,
        date_joined,
        type
        -- has_accepted_tos,
        -- has_newsletter_subscription,
        -- project_owner_plan
    FROM
        debug_users_vw
;


CREATE OR REPLACE TEMPORARY VIEW debug_projects_vw AS
    SELECT
        P.id AS project_id,
        P.name AS project_name,
        LOWER(U.username) AS project_owner_username,
        U.id AS project_owner_id,
        -- UAT.code AS project_owner_plan,
        P.file_storage_bytes,
        P.overwrite_conflicts,
        P.is_public,
        P.project_filename,
        P.repackaging_cache_expire,
        P.created_at,
        P.data_last_packaged_at,
        P.data_last_updated_at,
        P.last_package_job_id,
        P.description,
        P.thumbnail_uri,
        COALESCE(J.jobs_count, 0) AS jobs_count,
        COALESCE(J.process_projectfile_jobs_count, 0) AS process_projectfile_jobs_count,
        COALESCE(J.package_jobs_count, 0) AS package_jobs_count,
        COALESCE(J.apply_jobs_count, 0) AS apply_jobs_count,
        jsonb_pretty(J.jobs) AS jobs,
        jsonb_pretty(P.project_details) AS project_details
    FROM
        core_project P
        JOIN core_user U ON U.id = P.owner_id
        JOIN core_useraccount UA ON UA.user_id = U.id
        -- JOIN subscription_plan UAT ON UAT.id = UA.plan_id
        LEFT JOIN (
            SELECT
                project_id,
                COUNT(J2) AS jobs_count,
                COUNT(J2) FILTER (WHERE J2.type = 'process_projectfile') AS process_projectfile_jobs_count,
                COUNT(J2) FILTER (WHERE J2.type = 'package') AS package_jobs_count,
                COUNT(J2) FILTER (WHERE J2.type = 'apply_job') AS apply_jobs_count,
                jsonb_agg(J2) AS jobs
            FROM (
                    SELECT
                        J1.id AS job_id,
                        J1.project_id,
                        J1.type,
                        J1.created_at,
                        LOWER(U1.username) AS created_by,
                        J1.created_by_id
                    FROM
                        core_job J1
                        JOIN core_user U1 ON U1.id = J1.created_by_id
            ) J2
            GROUP BY project_id
        ) J ON J.project_id = P.id
;


CREATE OR REPLACE TEMPORARY VIEW debug_projects_slim_vw AS
    SELECT
        project_id,
        project_name,
        project_owner_username,
        project_owner_id,
        -- project_owner_plan,
        file_storage_bytes,
        overwrite_conflicts,
        is_public,
        project_filename,
        repackaging_cache_expire,
        created_at,
        data_last_packaged_at,
        data_last_updated_at,
        last_package_job_id,
        description,
        thumbnail_uri
    FROM
        debug_projects_vw
;


CREATE OR REPLACE TEMPORARY VIEW debug_deltas_vw AS
    SELECT
        P.id AS project_id,
        P.name AS project_name,
        LOWER(U.username) AS project_owner_username,
        U.id AS project_owner_id,
        -- UAT.code AS project_owner_plan,
        D.id AS delta_id,
        deltafile_id AS deltafile_id,
        D.last_status,
        jsonb_pretty(D.content) AS content,
        jsonb_pretty(D.last_feedback) AS last_feedback,
        D.last_modified_pk,
        LOWER(U1.username) AS created_by,
        D.created_by_id,
        D.created_at,
        LOWER(U2.username) AS last_apply_attempt_by,
        D.last_apply_attempt_by_id,
        D.last_apply_attempt_at AS last_apply_attempt_at,
        ST_AsText(D.old_geom) AS old_geom,
        ST_AsText(D.new_geom) AS new_geom,
        COALESCE(AJ.apply_jobs_count, 0) AS apply_jobs_count,
        jsonb_pretty(AJ.jobs) AS apply_jobs
    FROM
        core_delta D
        JOIN core_project P ON P.id = D.project_id
        JOIN core_user U ON U.id = P.owner_id
        JOIN core_useraccount UA ON UA.user_id = U.id
        -- JOIN subscription_plan UAT ON UAT.id = UA.plan_id
        JOIN core_user U1 ON U1.id = D.created_by_id
        LEFT JOIN core_user U2 ON U2.id = D.last_apply_attempt_by_id
        LEFT JOIN (
            SELECT
                project_id,
                delta_id,
                COUNT(J2) AS apply_jobs_count,
                jsonb_agg(J2) AS jobs
            FROM (
                SELECT
                    AJD.id,
                    AJD.status,
                    AJD.delta_id,
                    AJD.apply_job_id,
                    AJD.modified_pk,
                    J1.project_id,
                    J1.created_at AS apply_job_created_at,
                    LOWER(U1.username) AS apply_job_created_by,
                    J1.created_by_id AS apply_job_created_by_id
                FROM core_applyjobdelta AJD
                JOIN core_job J1 ON J1.id = AJD.apply_job_id
                JOIN core_delta D1 ON D1.id = AJD.delta_id
                JOIN core_user U1 ON U1.id = D1.created_by_id
            ) J2
            GROUP BY J2.project_id, J2.delta_id
        ) AJ ON AJ.project_id = D.project_id AND AJ.delta_id = D.id
    ORDER BY D.created_at DESC
;


CREATE OR REPLACE TEMPORARY VIEW debug_deltas_slim_vw AS
    SELECT
        project_id,
        project_name,
        project_owner_username,
        project_owner_id,
        -- project_owner_plan,
        delta_id,
        deltafile_id,
        last_status,
        last_modified_pk,
        created_by,
        created_by_id,
        created_at,
        last_apply_attempt_by,
        last_apply_attempt_by_id,
        last_apply_attempt_at
    FROM debug_deltas_vw
;


CREATE OR REPLACE TEMPORARY VIEW debug_jobs_vw AS
    SELECT
        P.id AS project_id,
        P.name AS project_name,
        LOWER(U.username) AS project_owner_username,
        U.id AS project_owner_id,
        -- UAT.code AS project_owner_plan,
        J.id AS job_id,
        J.type,
        J.status,
        jsonb_pretty(J.feedback) AS feedback,
        J.output,
        LOWER(U1.username) AS created_by,
        J.created_by_id,
        J.created_at,
        J.started_at,
        J.finished_at,
        EXTRACT (epoch FROM (J.started_at - J.created_at)) AS wait_s,
        EXTRACT (epoch FROM (J.finished_at - J.started_at)) AS duration_s,
        AJ.overwrite_conflicts,
        COALESCE(D.count, 0) AS delta_count,
        jsonb_pretty(D.delta_ids) AS delta_ids

    FROM
        core_job J
        JOIN core_project P ON P.id = J.project_id
        JOIN core_user U ON U.id = P.owner_id
        JOIN core_useraccount UA ON UA.user_id = U.id
        -- JOIN subscription_plan UAT ON UAT.id = UA.plan_id
        JOIN core_user U1 ON U1.id = J.created_by_id
        LEFT JOIN core_applyjob AJ ON AJ.job_ptr_id = J.id
        LEFT JOIN (
            SELECT
                project_id,
                COUNT(*) AS count,
                jsonb_agg(id) AS delta_ids
            FROM core_delta D
            GROUP BY project_id
        ) D ON D.project_id = J.project_id
    ORDER BY J.created_at DESC
;


CREATE OR REPLACE TEMPORARY VIEW debug_jobs_slim_vw AS
    SELECT
        project_id,
        project_name,
        project_owner_username,
        project_owner_id,
        -- project_owner_plan,
        job_id,
        type,
        status,
        created_by,
        created_by_id,
        created_at,
        started_at,
        finished_at,
        wait_s,
        duration_s,
        overwrite_conflicts,
        delta_count
    FROM debug_jobs_vw
;
