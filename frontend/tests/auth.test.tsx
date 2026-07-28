import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { apiMock, mockApiModule } from "./mocks/api";

vi.mock("../src/api", () => mockApiModule());
import App from "../src/App";

const admin = { id: "a", username: "admin", role: "admin" as const, is_active: true, must_change_password: false, created_at: "2026-01-01", updated_at: "2026-01-01", last_login_at: null };
const common = { ...admin, id: "u", username: "common", role: "user" as const };
const renderAt = (path: string) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

describe("autenticação local", () => {
  beforeEach(() => { vi.clearAllMocks(); apiMock.authMe.mockResolvedValue(admin); apiMock.authChangePassword.mockResolvedValue(admin); apiMock.adminListUsers.mockResolvedValue([admin, common]); });

  it("exibe login sem cadastro público quando não autenticado", async () => {
    apiMock.authMe.mockRejectedValue(new Error("401")); renderAt("/");
    expect(await screen.findByTestId("login-submit")).toBeInTheDocument();
    expect(screen.queryByText(/cadastro|registrar/i)).not.toBeInTheDocument();
  });

  it("login envia credenciais, não usa storage e abre a aplicação", async () => {
    apiMock.authMe.mockRejectedValue(new Error("401")); apiMock.authLogin.mockResolvedValue(admin);
    const local = vi.spyOn(Storage.prototype, "setItem"); renderAt("/");
    fireEvent.change(await screen.findByTestId("login-username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("login-password"), { target: { value: "secret-value" } });
    fireEvent.click(screen.getByTestId("login-submit"));
    await waitFor(() => expect(apiMock.authLogin).toHaveBeenCalledWith("admin", "secret-value"));
    expect(await screen.findByText("Painel inicial")).toBeInTheDocument(); expect(local).not.toHaveBeenCalled(); local.mockRestore();
  });

  it("login inválido mostra erro controlado", async () => {
    apiMock.authMe.mockRejectedValue(new Error("401")); apiMock.authLogin.mockRejectedValue(new Error("401")); renderAt("/login");
    fireEvent.change(await screen.findByTestId("login-username"), { target: { value: "x" } }); fireEvent.change(screen.getByTestId("login-password"), { target: { value: "x" } }); fireEvent.click(screen.getByTestId("login-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciais inválidas");
  });

  it("/auth/me restaura sessão sem consultar o PI", async () => {
    renderAt("/"); expect(await screen.findByText("admin")).toBeInTheDocument(); expect(apiMock.authMe).toHaveBeenCalledOnce(); expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("logout limpa estado e não consulta ou cancela no PI", async () => {
    apiMock.authLogout.mockResolvedValue(undefined); renderAt("/"); fireEvent.click(await screen.findByText("Sair"));
    expect(await screen.findByTestId("login-submit")).toBeInTheDocument(); expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled(); expect(apiMock.cancelQuery).not.toHaveBeenCalled();
  });

  it("usuário comum não vê nem acessa administração", async () => {
    apiMock.authMe.mockResolvedValue(common); renderAt("/admin/usuarios"); expect(await screen.findByText("Painel inicial")).toBeInTheDocument(); expect(screen.queryByText("Gestão de usuários")).not.toBeInTheDocument();
  });

  it("administrador lista usuários e alterações não consultam o PI", async () => {
    renderAt("/admin/usuarios"); expect(await screen.findByText("Gestão de usuários")).toBeInTheDocument(); expect(screen.getByText("common")).toBeInTheDocument(); expect(apiMock.adminListUsers).toHaveBeenCalledOnce(); expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("formulários de senha usam limites de 5 a 128 caracteres", async () => {
    renderAt("/admin/usuarios");
    fireEvent.click(await screen.findByText("Novo usuário"));
    const initial = screen.getByRole("dialog").querySelector('input[type="password"]') as HTMLInputElement;
    expect(initial.minLength).toBe(5); expect(initial.maxLength).toBe(128);
    fireEvent.click(screen.getByText("Cancelar"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("Alterar senha"));
    const own = screen.getByRole("dialog").querySelectorAll('input[type="password"]')[1] as HTMLInputElement;
    expect(own.minLength).toBe(5); expect(own.maxLength).toBe(128);
  });

  it("evento 401 encerra a sessão e redireciona", async () => {
    renderAt("/"); await screen.findByText("admin"); window.dispatchEvent(new CustomEvent("pads:unauthorized")); expect(await screen.findByTestId("login-submit")).toBeInTheDocument();
  });

  it("usuário pendente não contorna a troca obrigatória por URL direta", async () => {
    apiMock.authMe.mockResolvedValue({ ...common, must_change_password: true });
    renderAt("/analises/visualizacao");
    expect(await screen.findByText("Troca obrigatória de senha")).toBeInTheDocument();
    expect(screen.queryByTestId("data-visualization-page")).not.toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("troca obrigatória confirma a senha e libera a aplicação", async () => {
    const pending = { ...common, must_change_password: true };
    apiMock.authMe.mockResolvedValue(pending); apiMock.authChangePassword.mockResolvedValue(common);
    renderAt("/trocar-senha");
    fireEvent.change(await screen.findByTestId("required-current-password"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("required-new-password"), { target: { value: "nova1" } });
    fireEvent.change(screen.getByTestId("required-confirm-password"), { target: { value: "nova1" } });
    fireEvent.click(screen.getByRole("button", { name: "Alterar senha" }));
    await waitFor(() => expect(apiMock.authChangePassword).toHaveBeenCalledWith("admin", "nova1"));
    expect(await screen.findByText("Painel inicial")).toBeInTheDocument();
  });
});
