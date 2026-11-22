import { lazy, type ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

import { RequirePermission } from "../../auth/RequirePermission";

/** One lazy chunk per page. Vite can only split these if the import()
 *  argument is a static literal. */
const BackupsPage = lazy(() => import("./pages/BackupsPage"));
const SchedulesPage = lazy(() => import("./pages/SchedulesPage"));
const ArchivalPage = lazy(() => import("./pages/ArchivalPage"));
const ArchivalReviewPage = lazy(() => import("./pages/ArchivalReviewPage"));
const ClassificationPage = lazy(() => import("./pages/ClassificationPage"));
const EncryptionPage = lazy(() => import("./pages/EncryptionPage"));
const SpecialArchivalPage = lazy(() => import("./pages/SpecialArchivalPage"));
const RestorationPage = lazy(() => import("./pages/RestorationPage"));
const StoragePage = lazy(() => import("./pages/StoragePage"));
const StorageApprovalsPage = lazy(() => import("./pages/StorageApprovalsPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));
const SecurityPage = lazy(() => import("./pages/SecurityPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));

/** Paths are RELATIVE — the shell mounts them under /badms.
 *
 *  Every entry here matches a nav item in the server's registry.py. */
// An office page, for the roles its nav item's required_permission names (registry.py).
function office(permission: string, page: ReactNode) {
  return <RequirePermission permission={permission}>{page}</RequirePermission>;
}

export const routes: RouteObject[] = [
  { index: true, element: <Navigate to="backups" replace /> },
  { path: "backups", element: <BackupsPage /> },
  { path: "schedules",
    element: office("badms.schedule.manage", <SchedulesPage />) },
  { path: "archival", element: <ArchivalPage /> },
  { path: "archival-review",
    element: office("badms.archival.decide", <ArchivalReviewPage />) },
  { path: "classification",
    element: office("badms.archival.classify", <ClassificationPage />) },
  { path: "encryption",
    element: office("badms.encryption.manage", <EncryptionPage />) },
  { path: "special-archival",
    element: office("badms.special_archival.perform",
      <SpecialArchivalPage />) },
  { path: "restoration", element: <RestorationPage /> },
  { path: "storage", element: <StoragePage /> },
  { path: "storage-approvals",
    element: office("badms.storage.decide", <StorageApprovalsPage />) },
  { path: "audit", element: office("badms.audit.view", <AuditPage />) },
  { path: "security",
    element: office("badms.security.audit", <SecurityPage />) },
  { path: "reports",
    element: office("badms.report.department", <ReportsPage />) },
];
