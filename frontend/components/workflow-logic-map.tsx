"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, Background, Controls, Position, type Node, type Edge, type ReactFlowInstance } from "@xyflow/react";

import { Workflow, ChevronRight, ArrowRight } from "lucide-react";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Empty } from "@/components/ui";
export type WorkflowLogic={available:boolean;reason?:string;node_count?:number;stages?:{id:string;title:string;nodes:{id:string;name:string;type:string;disabled:boolean}[]}[];edges?:{source:string;target:string;label:string}[]};
export default function WorkflowLogicMap({logic}:{logic?:WorkflowLogic}){
 const [selected,setSelected]=useState("");
 const canvas=useRef<HTMLDivElement>(null);
 const flow=useRef<ReactFlowInstance|null>(null);
 useEffect(()=>{const observer=new ResizeObserver(()=>{if(canvas.current?.clientWidth)flow.current?.fitView({padding:0.2})});if(canvas.current)observer.observe(canvas.current);return()=>observer.disconnect()},[]);
 const stages=logic?.stages??[];
 const links=logic?.edges??[];
 const nodes=useMemo<Node[]>(()=>{
  const rank=new Map<string,number>();
  const degree=new Map(stages.map(s=>[s.id,links.filter(e=>e.target===s.id&&e.source!==e.target).length]));
  const queue=stages.filter(s=>!degree.get(s.id)).map(s=>s.id);
  for(const id of queue){rank.set(id,rank.get(id)??0);for(const e of links.filter(e=>e.source===id&&e.target!==id)){rank.set(e.target,Math.max(rank.get(e.target)??0,(rank.get(id)??0)+1));degree.set(e.target,(degree.get(e.target)??1)-1);if(degree.get(e.target)===0)queue.push(e.target)}}
  const rows=new Map<number,number>();
  return stages.map((s,i)=>{const column=rank.get(s.id)??Math.floor(i/3);const row=rows.get(column)??0;rows.set(column,row+1);return {id:s.id,width:205,height:100,position:{x:column*250,y:row*135},sourcePosition:Position.Right,targetPosition:Position.Left,className:`logic-stage${selected===s.id?" is-selected":""}`,data:{label:<button type="button" className="logic-stage-button nodrag" onClick={()=>setSelected(s.id)} aria-label={`Expand stage: ${s.title}`} aria-expanded={selected===s.id}><span><Workflow size={15}/>{s.nodes.length} {s.nodes.length===1?"node":"nodes"}<ChevronRight size={13}/></span><strong>{s.title}</strong></button>}}})
 },[stages,links,selected]);
 const edges:Edge[]=links.map((e,i)=>({id:`edge-${i}`,source:e.source,target:e.target,label:e.label,type:"smoothstep",style:{stroke:"var(--muted)"},labelStyle:{fill:"var(--text)",fontSize:10},labelBgStyle:{fill:"var(--surface)"}}));
 return <section className="card workflow-logic mb-6">
  <div className="section-heading"><div><h2>Workflow logic</h2><p>{logic?.available?`${logic.node_count} actual nodes · ${stages.length} stages` : "Source workflow definition"}</p></div></div>
  {!logic?.available?<Empty title="Workflow map unavailable" hint={logic?.reason??"Sync an API-connected n8n instance to load its workflow definition."}/>:<>
   <div className="logic-canvas" ref={canvas}><ReactFlow onInit={instance=>{flow.current=instance}} onNodeClick={(_,node)=>setSelected(node.id)} nodes={nodes} edges={edges} fitView fitViewOptions={{padding:0.2}} minZoom={0.35} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} elementsSelectable={false} edgesFocusable={false} zoomOnScroll={false} preventScrolling={false} ><Background color="var(--border)" gap={18} size={1}/><Controls showInteractive={false}/></ReactFlow></div>
   <div className="logic-stage-list"><p>Expand a stage to see its nodes. Short sequences are grouped; branches and merges stay separate.</p><Accordion type="single" collapsible value={selected} onValueChange={setSelected}>{stages.map((s,index)=><AccordionItem key={s.id} value={s.id}><AccordionTrigger><span className="logic-list-title"><span className="mono">{String(index+1).padStart(2,"0")}</span>{s.title}<span className="logic-node-count">{s.nodes.length} {s.nodes.length===1?"node":"nodes"}</span></span></AccordionTrigger><AccordionContent><ol className="logic-actual-nodes">{s.nodes.map((n,i)=><li key={n.id}><span className="logic-node-order">{i+1}</span><div><strong>{n.name}</strong><span>{n.type.split(".").pop()}{n.disabled?" · Disabled":""}</span></div>{i<s.nodes.length-1&&<ArrowRight size={13} className="muted"/>}</li>)}</ol>{links.filter(e=>e.source===s.id).map((e,i)=><p key={i} className="logic-connection">{e.label?`${e.label} → `:"Next → "}{stages.find(target=>target.id===e.target)?.title}</p>)}</AccordionContent></AccordionItem>)}</Accordion></div>
   <div className="logic-foot">Read-only map from the last sync. Node parameters, credentials, and pinned data are excluded.</div>
  </>}
 </section>;
}
