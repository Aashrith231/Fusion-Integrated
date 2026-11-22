import { lazy } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

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
export const routes: RouteObject[] = [
  { index: true, element: <Navigate to="backups" replace /> },
  { path: "backups", element: <BackupsPage /> },
  { path: "schedules", element: <SchedulesPage /> },
  { path: "archival", element: <ArchivalPage /> },
  { path: "archival-review", element: <ArchivalReviewPage /> },
  { path: "classification", element: <ClassificationPage /> },
  { path: "encryption", element: <EncryptionPage /> },
  { path: "special-archival", element: <SpecialArchivalPage /> },
  { path: "restoration", element: <RestorationPage /> },
  { path: "storage", element: <StoragePage /> },
  { path: "storage-approvals", element: <StorageApprovalsPage /> },
  { path: "audit", element: <AuditPage /> },
  { path: "security", element: <SecurityPage /> },
  { path: "reports", element: <ReportsPage /> },
];
