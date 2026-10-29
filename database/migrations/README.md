# Database migrations

The web container runs `python manage.py migrate` every time it starts. The runner
(`studenthub/migrations.py`) applies each `NNN_description.sql` file in this folder once,
in numeric order, and records it in the `schema_migrations` table with a checksum.

## Adding a schema change

1. Create the next file, for example `002_add_assignment_grade.sql`:

   ```sql
   -- 002_add_assignment_grade.sql
   ALTER TABLE assignments ADD COLUMN grade VARCHAR(10) NULL AFTER status;
   ```

2. Update the Python code that uses the new column, and add tests.
3. Run the tests (`.\scripts\run-tests.ps1`), then rebuild locally (`docker compose up -d --build`).
   The new migration is applied automatically on start; check with
   `docker compose exec web python manage.py migration-status`.
4. Commit and push. Production applies the same file during deployment.

## Rules

* **Never edit or delete a migration that has been applied anywhere.** The runner refuses
  to start when an applied file's checksum changes. Fix mistakes with a new migration.
* **Additive changes only** (new tables, new nullable columns, new indexes). Old application
  versions must keep working with the new schema, so a deployment rollback stays safe.
  Never drop columns or tables that the previous release still uses.
* One statement per line-ending `;`. Do not use `DELIMITER` or stored procedures.
* MySQL commits DDL statements immediately, so keep one logical change per file.
