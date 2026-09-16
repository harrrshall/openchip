module tb;
reg [4:1] x=0;wire f;TopModule dut(x,f);
integer i,samples=0,mismatches=0;reg expected,care;
initial begin
for(i=0;i<16;i=i+1)begin
 x=i;#1;care=1;
 case(i)
 4,6,11,12,14: expected=1;
 2,7,8,9: expected=0;
 default:begin care=0;expected=0;end
 endcase
 if(care)begin samples=samples+1;if(f !== expected)begin mismatches=mismatches+1;$display("MISMATCH x=%0d got=%b expected=%b",i,f,expected);end end
end
$display("KMAP_RESULT mismatches=%0d care_samples=%0d stimuli=16",mismatches,samples);
if(mismatches)$fatal(1,"Kmap mismatch");$finish;
end
endmodule
