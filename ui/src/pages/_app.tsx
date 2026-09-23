import type { AppProps } from "next/app";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import "../styles/globals.css";

export default function App({ Component, pageProps }: AppProps) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [user, setUser] = useState<any>(null);
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("github_token");
    const userData = localStorage.getItem("user");
    if (token && userData) {
      setIsLoggedIn(true);
      setUser(JSON.parse(userData));
    }

    // Handle OAuth callback
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (code && !token) {
      // Exchange code for token
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/github/callback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      })
        .then((r) => r.json())
        .then((data) => {
          localStorage.setItem("github_token", data.access_token);
          // Fetch user info
          return fetch("https://api.github.com/user", {
            headers: { Authorization: `Bearer ${data.access_token}` },
          });
        })
        .then((r) => r.json())
        .then((userData) => {
          localStorage.setItem("user", JSON.stringify(userData));
          setUser(userData);
          setIsLoggedIn(true);
          router.push("/dashboard");
        });
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("github_token");
    localStorage.removeItem("user");
    setIsLoggedIn(false);
    setUser(null);
    router.push("/");
  };

  if (!isLoggedIn && router.pathname !== "/") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <h1 className="text-4xl font-bold mb-4">B2B Pipeline Dashboard</h1>
          <p className="text-gray-600 mb-8">Sign in with GitHub to continue</p>
          <a
            href={`https://github.com/login/oauth/authorize?client_id=${process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID}&redirect_uri=${encodeURIComponent(
              typeof window !== "undefined" ? window.location.origin + "/?code=" : ""
            )}&scope=user:email`}
            className="inline-block px-6 py-3 bg-gray-900 text-white rounded-lg hover:bg-gray-800"
          >
            Sign in with GitHub
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {isLoggedIn && (
        <nav className="bg-white shadow-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between items-center py-4">
              <div className="flex gap-8">
                <Link href="/dashboard" className="text-sm font-medium text-gray-900 hover:text-gray-600">
                  Dashboard
                </Link>
                <Link href="/partners" className="text-sm font-medium text-gray-900 hover:text-gray-600">
                  Partners
                </Link>
                <Link href="/leads" className="text-sm font-medium text-gray-900 hover:text-gray-600">
                  Leads
                </Link>
                <Link href="/audit-log" className="text-sm font-medium text-gray-900 hover:text-gray-600">
                  Audit Log
                </Link>
                <Link href="/runs" className="text-sm font-medium text-gray-900 hover:text-gray-600">
                  Runs
                </Link>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-sm text-gray-600">{user?.login}</span>
                <button
                  onClick={handleLogout}
                  className="text-sm font-medium text-red-600 hover:text-red-500"
                >
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </nav>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Component {...pageProps} />
      </main>
    </div>
  );
}
