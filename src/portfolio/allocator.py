[apply patch]
*** Begin Patch
*** Update File: src/portfolio/allocator.py
@@
-import asyncio
-import logging
-from datetime import date, timedelta
-from typing import Any
-
-import numpy as np
-from sqlalchemy.ext.asyncio import AsyncSession
-
+import asyncio
+import logging
+from datetime import date, timedelta
+from typing import Any, Optional
+
+import numpy as np
+from sqlalchemy.engine import Engine
+from sqlalchemy.ext.asyncio import AsyncSession
+from sqlalchemy.orm import sessionmaker
@@
-    async def allocate_async(self, capital: float, db: AsyncSession | None = None) -> dict[str, Any]:
-        if db is not None:
-            logger.warning("allocate_async: AsyncSession ignored, using sync session via run_in_executor")
-        loop = asyncio.get_running_loop()
-        return await loop.run_in_executor(None, self.allocate, capital, None)
+    async def allocate_async(self, capital: float, db: Optional[AsyncSession] = None) -> dict[str, Any]:
+        """
+        Run the synchronous allocate() in a thread pool while ensuring the synchronous
+        SQLAlchemy Session is bound to the same underlying database engine as the
+        provided AsyncSession (if any). This avoids mixing AsyncSession with sync
+        DB operations which causes MissingGreenlet errors.
+        """
+        loop = asyncio.get_running_loop()
+
+        if db is not None:
+            # Try to derive the sync engine from the AsyncSession's bind (AsyncEngine)
+            try:
+                async_bind = db.get_bind()
+                sync_engine: Optional[Engine] = getattr(async_bind, "sync_engine", None)
+            except Exception:
+                sync_engine = None
+
+            if sync_engine is None:
+                # Fallback to global sync engine defined in connection module
+                from src.db.connection import sync_engine as _fallback_sync_engine
+
+                sync_engine = _fallback_sync_engine
+
+            SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)
+
+            def _run_with_sync_session():
+                with SyncSession() as sess:
+                    return self.allocate(capital, db=sess)
+
+            return await loop.run_in_executor(None, _run_with_sync_session)
+
+        # No AsyncSession provided - allocate() will create its own sync session as before
+        return await loop.run_in_executor(None, self.allocate, capital, None)
*** End Patch
