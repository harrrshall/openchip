`timescale 1ns/1ps
module tb;
 reg clk=0,rst=0,in_valid=0,out_ready=0;
 reg [7:0] in_data=0;
 wire in_ready,out_valid;
 wire [7:0] out_data;
 elastic_buffer dut(.clk(clk),.rst(rst),.in_valid(in_valid),.in_data(in_data),
 .in_ready(in_ready),.out_ready(out_ready),.out_valid(out_valid),.out_data(out_data));
 reg v1=0,v2=0;
 reg [7:0] d1=0,d2=0;
 reg r1,r2;
 reg [7:0] queue[0:65535];
 integer head=0,tail=0,accepted=0,delivered=0,cases=0,seq_id,j,i;
 reg [31:0] rng=32'h59615eab;
 task check_outputs;
 begin
   if(out_valid !== v2 || out_data !== d2 || in_ready !== (!v1 || !v2 || out_ready)) begin
     $display("FAIL case=%0d valid=%b/%b data=%h/%h ready=%b",cases,out_valid,v2,out_data,d2,in_ready);
     $fatal(1);
   end
 end
 endtask
 task step;
 input reset_bit,valid_bit,ready_bit;
 input [7:0] data_byte;
 begin
   clk=0; rst=reset_bit; in_valid=valid_bit; out_ready=ready_bit; in_data=data_byte;
   #2;
   if(cases>0) check_outputs;
   r2=!v2 || out_ready; r1=!v1 || r2;
   if(rst) begin head=0;tail=0;v1=0;v2=0;d1=0;d2=0;end
   else begin
     // Independent ordered queue checks transfers using external interface.
     if(out_valid && out_ready) begin
       if(head==tail || out_data !== queue[head]) begin
         $display("FAIL queue case=%0d head=%0d tail=%0d",cases,head,tail); $fatal(1);
       end
       head=head+1; delivered=delivered+1;
     end
     if(in_valid && in_ready) begin queue[tail]=in_data;tail=tail+1;accepted=accepted+1;end
     if(tail-head>2) begin $display("FAIL capacity");$fatal(1);end
     // Exact externally specified latency, empty-data hold, and reset semantics.
     if(r2) begin v2=v1;if(v1)d2=d1;end
     if(r1) begin v1=in_valid;if(in_valid)d1=in_data;end
   end
   clk=1;#2;check_outputs;cases=cases+1;
 end
 endtask
 initial begin
   step(1,0,0,0);
   // Every six-cycle valid/ready control history, independently reset and drained.
   for(seq_id=0;seq_id<4096;seq_id=seq_id+1) begin
     step(1,0,0,0);
     for(j=0;j<6;j=j+1) step(0,(seq_id>>(2*j))&1,(seq_id>>(2*j+1))&1,seq_id+j*37);
     step(0,0,1,0);step(0,0,1,0);step(0,0,1,0);
     if(head!=tail) begin $display("FAIL drain");$fatal(1);end
   end
   // Sustained throughput, prolonged output stall and reset with both slots full.
   for(i=0;i<512;i=i+1) step(0,1,1,i);
   for(i=0;i<32;i=i+1) step(0,1,0,i);
   step(1,1,0,255);step(0,0,1,0);step(0,0,1,0);
   for(i=0;i<10000;i=i+1) begin
     rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
     step(rng[7:0]==0,rng[8],rng[9],rng[23:16]);
   end
   step(0,0,1,0);step(0,0,1,0);step(0,0,1,0);
   if(head!=tail) begin $display("FAIL final drain");$fatal(1);end
   $display("PASS cases=%0d exhaustive_control_histories=4096 accepted=%0d delivered=%0d",cases,accepted,delivered);
   $finish;
 end
endmodule
