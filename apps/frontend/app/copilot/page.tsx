import { Screen } from "@/components/layout/Screen";
import { PhasePlaceholder } from "@/components/ui/PhasePlaceholder";

export default function Page() {
  return (
    <Screen title="Copilot">
      <PhasePlaceholder
        phase={10}
        title="AI Operations Copilot"
        items={["Chat with streaming answers", "Tool trace, source cards, approval cards", "Agent step timeline"]}
      />
    </Screen>
  );
}
