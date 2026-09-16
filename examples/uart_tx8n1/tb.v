module tb;
parameter D=4;
reg clk=0,reset=0,start=0;reg[7:0] data=0;
wire tx,busy,done;
uart_tx8n1 #(.CLKS_PER_BIT(D)) dut(.clk(clk),.reset(reset),.start(start),.data(data),.tx(tx),.busy(busy),.done(done));
always #5 clk=~clk;
integer left=0,exp_tx=1,exp_busy=0,exp_done=0;
integer checks=0,errors=0,word,k;
reg[9:0] frame;
task cycle;input integer rst,go,payload;begin
 @(negedge clk);reset=rst;start=go;data=payload;
 exp_done=0;
 if(rst)begin left=0;exp_tx=1;exp_busy=0;end
 else if(left>0)begin
  left=left-1;
  if(left==0)begin exp_tx=1;exp_busy=0;exp_done=1;end
  else begin exp_tx=frame[(10*D-left)/D];exp_busy=1;end
 end
 else if(go)begin frame={1'b1,payload[7:0],1'b0};left=10*D;exp_tx=0;exp_busy=1;end
 else begin exp_tx=1;exp_busy=0;end
 @(posedge clk);#1;checks=checks+1;
 if(tx!==exp_tx[0] || busy!==exp_busy[0] || done!==exp_done[0])begin
  errors=errors+1;if(errors<8)$display("MISMATCH check=%0d got=%b%b%b expected=%b%b%b",checks,tx,busy,done,exp_tx[0],exp_busy[0],exp_done[0]);
 end
end endtask
initial begin
 cycle(1,1,255);cycle(0,0,0);
 for(word=0;word<256;word=word+1)begin
  cycle(0,1,word);
  for(k=0;k<10*D;k=k+1)cycle(0,1,word^k^255);
  cycle(0,0,word);
 end
 cycle(0,1,165);
 for(k=0;k<3*D;k=k+1)cycle(0,1,k);
 cycle(1,1,255);cycle(0,0,0);cycle(0,1,90);
 for(k=0;k<10*D;k=k+1)cycle(0,0,k);
 cycle(0,0,0);
 $display("INDEPENDENT_RESULT divisor=%0d mismatches=%0d samples=%0d bytes=256",D,errors,checks);$finish;
end
endmodule
