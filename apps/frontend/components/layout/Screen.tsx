import { Header } from "./Header";
import { StatusBar } from "./StatusBar";

export function Screen({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <Header title={title} />
      <StatusBar />
      <div className="min-h-0 flex-1 overflow-auto p-6">{children}</div>
    </>
  );
}
