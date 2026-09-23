import { useEffect } from "react";
import { useRouter } from "next/router";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("github_token");
    if (token) {
      router.push("/dashboard");
    }
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-r from-blue-600 to-blue-800">
      <div className="text-center text-white">
        <h1 className="text-5xl font-bold mb-4">B2B Pipeline Dashboard</h1>
        <p className="text-xl mb-8 opacity-90">Monitor and manage your prospecting pipeline</p>
        <a
          href={`https://github.com/login/oauth/authorize?client_id=${process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID}&redirect_uri=${encodeURIComponent(
            typeof window !== "undefined" ? window.location.origin : ""
          )}&scope=user:email`}
          className="inline-block px-8 py-3 bg-white text-blue-600 font-semibold rounded-lg hover:bg-gray-100 transition"
        >
          Sign in with GitHub
        </a>
      </div>
    </div>
  );
}
