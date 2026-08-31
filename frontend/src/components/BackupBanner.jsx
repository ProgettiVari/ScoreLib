import React from "react";
import { AlertTriangle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export default function BackupBanner() {
  const { user } = useAuth();
  return null; // Disabilitato in modalità gruppo unico
}
