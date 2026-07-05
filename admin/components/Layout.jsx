import Head from "next/head";
import Sidebar from "./Sidebar";

export default function Layout({ title, children }) {
  return (
    <div className="min-h-screen bg-bg flex">
      <Head>
        <title>{title ? `${title} · Al-Madih Admin` : "Al-Madih Admin"}</title>
      </Head>
      <Sidebar />
      <main className="flex-1 min-w-0 p-6 md:p-8">
        {title && <h1 className="text-2xl font-semibold text-gray-100 mb-6">{title}</h1>}
        {children}
      </main>
    </div>
  );
}
