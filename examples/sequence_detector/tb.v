module tb;
reg clk=0,reset=0,data=0;wire start_shifting;
TopModule dut(clk,reset,data,start_shifting);
reg [3:0] hist=0;reg expected=0,known=0;
integer p,i,cases=0,mismatches=0;
task compare;begin
 if(known)begin cases=cases+1;if(start_shifting !== expected)begin
 mismatches=mismatches+1;if(mismatches<5)$display("MISMATCH pattern=%0d step=%0d got=%b expected=%b",p,i,start_shifting,expected);
 end end
end endtask
task tick;input bit_value;input rst_value;begin
 clk=0;data=bit_value;reset=rst_value;#2;compare;
 clk=1;if(reset)begin hist=0;expected=0;known=1;end
 else begin hist={hist[2:0],data};if(hist==4'b1101)expected=1;end
 #2;compare;clk=0;#1;
end endtask
initial begin
 tick(0,1);
 for(p=0;p<4096;p=p+1)begin
 tick(0,1);
 for(i=11;i>=0;i=i-1)tick((p>>i)&1,0);
 tick(0,0);tick(0,0);tick(1,0);tick(0,1);
 end
 $display("SEQUENCE_RESULT mismatches=%0d samples=%0d histories=4096",mismatches,cases);
 if(mismatches)$fatal(1,"sequence mismatch");$finish;
end
endmodule
