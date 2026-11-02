"use client";
import { useSession } from "@/lib/session";
import { fmtDateTime as formatDate } from "@/lib/api";
export function useWorkspaceTime(){
 const {session,workspaceId}=useSession();
 const candidate=session?.memberships.find(m=>m.id===workspaceId)?.timezone||"UTC";
 let timeZone=candidate;
 try{new Intl.DateTimeFormat(undefined,{timeZone}).format()}catch{timeZone="UTC"}
 return {timeZone,fmtDateTime:(iso?:string|null)=>formatDate(iso,timeZone)};
}
