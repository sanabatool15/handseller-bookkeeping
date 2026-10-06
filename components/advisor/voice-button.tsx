"use client";

import { useEffect } from "react";
import SpeechRecognition, {
  useSpeechRecognition,
} from "react-speech-recognition";
import { Mic } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function VoiceButton({
  onTranscript,
}: {
  onTranscript: (text: string) => void;
}) {
  const { transcript, listening, resetTranscript, browserSupportsSpeechRecognition } =
    useSpeechRecognition();

  useEffect(() => {
    if (transcript) onTranscript(transcript);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcript]);

  if (!browserSupportsSpeechRecognition) {
    return null;
  }

  function toggle() {
    if (listening) {
      SpeechRecognition.stopListening();
    } else {
      resetTranscript();
      SpeechRecognition.startListening({ continuous: true });
    }
  }

  return (
    <Button
      type="button"
      variant={listening ? "accent" : "outline"}
      size="icon"
      onClick={toggle}
      className={cn(listening && "animate-pulse")}
      title={listening ? "Stop listening" : "Speak your entry"}
    >
      <Mic className="h-4 w-4" />
    </Button>
  );
}
