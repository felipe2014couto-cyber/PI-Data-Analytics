import { Navigate, Route, Routes } from "react-router-dom";

import { MainLayout } from "./layouts/MainLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { EquipmentsPage } from "./pages/EquipmentsPage";
import { SectionsPage } from "./pages/SectionsPage";
import { VariableTypesPage } from "./pages/VariableTypesPage";
import { PiTagsPage } from "./pages/PiTagsPage";
import { DataVisualizationPage } from "./pages/DataVisualizationPage";
import { CepAnalysisPage } from "./pages/CepAnalysisPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { LoginPage } from "./pages/LoginPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { RequiredPasswordChangePage } from "./pages/RequiredPasswordChangePage";

export default function App() {
  return (
    <ErrorBoundary><AuthProvider>
      <Routes>
        <Route path="login" element={<LoginPage />} />
        <Route path="trocar-senha" element={<RequiredPasswordChangePage />} />
        <Route element={<ProtectedRoute />}><Route element={<MainLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="cadastros/equipamentos" element={<EquipmentsPage />} />
          <Route path="cadastros/secoes" element={<SectionsPage />} />
          <Route path="cadastros/tipos-variavel" element={<VariableTypesPage />} />
          <Route path="cadastros/tags-pi" element={<PiTagsPage />} />
          <Route path="analises/visualizacao" element={<DataVisualizationPage />} />
          <Route path="analises/cep" element={<CepAnalysisPage />} />
          <Route element={<ProtectedRoute admin />}><Route path="admin/usuarios" element={<AdminUsersPage />} /></Route>
          <Route path="*" element={<NotFoundPage />} />
          <Route path="/redirect" element={<Navigate to="/" replace />} />
        </Route></Route>
      </Routes>
    </AuthProvider></ErrorBoundary>
  );
}
