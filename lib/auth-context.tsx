"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { api } from "./api-client";
import { AuthResponse, Org, User } from "./types";

interface AuthContextValue {
  user: User | null;
  org: Org | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    orgName: string,
    fullName?: string
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [org, setOrg] = useState<Org | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const storedUser = localStorage.getItem("user");
    const storedOrg = localStorage.getItem("org");
    const token = localStorage.getItem("access_token");
    if (token && storedUser) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time hydration from localStorage on mount
      setUser(JSON.parse(storedUser));
      if (storedOrg) setOrg(JSON.parse(storedOrg));
    }
    setLoading(false);
  }, []);

  function persist(res: AuthResponse) {
    localStorage.setItem("access_token", res.access_token);
    localStorage.setItem("user", JSON.stringify(res.user));
    if (res.org) localStorage.setItem("org", JSON.stringify(res.org));
    setUser(res.user);
    if (res.org) setOrg(res.org);
  }

  async function login(email: string, password: string) {
    const res = await api.post<AuthResponse>(
      "/auth/login",
      { email, password },
      { auth: false }
    );
    persist(res);
    router.push("/dashboard");
  }

  async function register(
    email: string,
    password: string,
    orgName: string,
    fullName?: string
  ) {
    const res = await api.post<AuthResponse>(
      "/auth/register",
      { email, password, org_name: orgName, full_name: fullName ?? null },
      { auth: false }
    );
    persist(res);
    router.push("/dashboard");
  }

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    localStorage.removeItem("org");
    setUser(null);
    setOrg(null);
    router.push("/login");
  }

  return (
    <AuthContext.Provider
      value={{ user, org, loading, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
