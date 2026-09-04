# BPMN 内嵌预览

# 引用独立 BPMN 文件

```bpmn-file
./sample-process.bpmn
```

```bpmn
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_1" targetNamespace="https://clawmate.local/bpmn">
  <bpmn:process id="Process_1" isExecutable="false"><bpmn:startEvent id="StartEvent_1" name="开始" /><bpmn:task id="Task_1" name="处理" /><bpmn:endEvent id="EndEvent_1" name="完成" /><bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1" /><bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="EndEvent_1" /></bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1"><bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1"><bpmndi:BPMNShape id="StartEvent_1_di" bpmnElement="StartEvent_1"><dc:Bounds x="120" y="100" width="36" height="36" /></bpmndi:BPMNShape><bpmndi:BPMNShape id="Task_1_di" bpmnElement="Task_1"><dc:Bounds x="220" y="78" width="100" height="80" /></bpmndi:BPMNShape><bpmndi:BPMNShape id="EndEvent_1_di" bpmnElement="EndEvent_1"><dc:Bounds x="390" y="100" width="36" height="36" /></bpmndi:BPMNShape><bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1"><di:waypoint x="156" y="118" /><di:waypoint x="220" y="118" /></bpmndi:BPMNEdge><bpmndi:BPMNEdge id="Flow_2_di" bpmnElement="Flow_2"><di:waypoint x="320" y="118" /><di:waypoint x="390" y="118" /></bpmndi:BPMNEdge></bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>
```
