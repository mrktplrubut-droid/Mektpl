import asyncio
from database import get_pool


async def auto_delete_worker():

    print("🗑 Auto delete worker running...")

    while True:

        try:

            pool = await get_pool()

            rows = await pool.fetch(
                """
                SELECT 
                    id,
                    code
                FROM codes
                WHERE expires_at IS NOT NULL
                AND expires_at < NOW()
                """
            )

            for row in rows:

                code_id = row["id"]
                code = row["code"]

                # hapus media terkait
                await pool.execute(
                    """
                    DELETE FROM medias
                    WHERE code_id=$1
                    """,
                    code_id
                )

                # hapus code
                await pool.execute(
                    """
                    DELETE FROM codes
                    WHERE id=$1
                    """,
                    code_id
                )

                print(
                    f"🗑 Deleted expired code: {code}"
                )

        except Exception as e:
            print(
                "AUTO DELETE ERROR:",
                e
            )

        await asyncio.sleep(60)
