#include <metal_stdlib>
using namespace metal;
constant float PI = 3.14159265358979323846f;
float3 mv(const device float* m, float3 v) {
    return float3(dot(float3(m[0],m[1],m[2]),v),dot(float3(m[3],m[4],m[5]),v),dot(float3(m[6],m[7],m[8]),v));
}
float3 mtv(const device float* m, float3 v) {
    return float3(dot(float3(m[0],m[3],m[6]),v),dot(float3(m[1],m[4],m[7]),v),dot(float3(m[2],m[5],m[8]),v));
}
float smooth(float a) { a=clamp(a,0.0f,1.0f);return a*a*(3-2*a); }
// Same 1/32 coordinate table as OpenCV INTER_LINEAR, wrap longitude only.
float field(const device float* a,int base,int w,int h,int channels,int c,float x,float y) {
    x=fmod(fmod(x,float(w))+w,float(w)); y=clamp(y,0.0f,float(h-1));
    x=rint(x*32)/32; y=rint(y*32)/32;
    int ix=int(floor(x)),iy=int(floor(y)); float dx=x-ix,dy=y-iy;
    int x0=ix%w,x1=(ix+1)%w,y0=min(iy,h-1),y1=min(iy+1,h-1);
    float p=a[base+(y0*w+x0)*channels+c],q=a[base+(y0*w+x1)*channels+c];
    float r=a[base+(y1*w+x0)*channels+c],s=a[base+(y1*w+x1)*channels+c];
    return mix(mix(p,q,dx),mix(r,s,dx),dy);
}
float3 project(float3 ray,const device float* l) {
    ray=normalize(ray); float den=ray.z+l[0]; float x=ray.x/den,y=ray.y/den;
    float r2=x*x+y*y; float rad=1+l[5]*r2+l[6]*r2*r2+l[9]*r2*r2*r2;
    float u=l[1]*(x*rad+2*l[7]*x*y+l[8]*(r2+2*x*x))+l[3];
    float v=l[2]*(y*rad+l[7]*(r2+2*y*y)+2*l[8]*x*y)+l[4];
    bool valid=ray.z > -1/l[0] && den>0 && u>=0 && v>=0 && u<l[10]-1 && v<l[10]-1;
    return float3(u,v,valid?1.0f:0.0f);
}
float3 rotateRow(float3 ray, float row, const device float* track, int count) {
    float position=clamp(row,0.0f,1.0f)*(count-1);
    int lower=min(int(position),count-2); float fraction=position-lower;
    float4 a=float4(track[lower*4],track[lower*4+1],track[lower*4+2],track[lower*4+3]);
    float4 b=float4(track[lower*4+4],track[lower*4+5],track[lower*4+6],track[lower*4+7]);
    float4 q=normalize(mix(a,b,fraction)); float3 c=2*cross(q.xyz,ray);
    return ray+q.w*c+cross(q.xyz,c);
}
float3 projectScan(float3 ray,const device float* l,float3 vel,float readout,
                   const device float* track,int count) {
    float3 uv=project(ray,l); float speed=length(vel);
    if(readout==0) return uv;
    if(count>0) {
        for(int k=0;k<2;k++) uv=project(rotateRow(ray,uv.y/(l[10]-1),track,count),l);
        return uv;
    }
    if(speed<1e-8f) return uv;
    float3 axis=vel/speed,crossed=cross(axis,ray),axial=dot(ray,axis)*axis;
    for(int k=0;k<2;k++) {
        float angle=-speed*(clamp(uv.y/(l[10]-1),0.0f,1.0f)-0.5f)*readout;
        uv=project(ray*cos(angle)+crossed*sin(angle)+axial*(1-cos(angle)),l);
    }
    return uv;
}
float cubic(float x) {
    x=abs(x); const float A=-0.75f;
    return x<=1 ? ((A+2)*x-(A+3))*x*x+1 : x<2 ? ((A*x-5*A)*x+8*A)*x-4*A : 0;
}
float3 pixel(const device uchar* a,int w,int x,int y,bool high) {
    int n=(clamp(y,0,w-1)*w+clamp(x,0,w-1))*3;
    if(high) { const device ushort* b=(const device ushort*)a;return float3(b[n],b[n+1],b[n+2]); }
    return float3(a[n],a[n+1],a[n+2]);
}
float3 sample(const device uchar* a,int w,float2 uv,bool high) {
    uv=rint(uv*32)/32; int2 p=int2(floor(uv)); float2 d=uv-float2(p);float3 out=0;
    for(int y=-1;y<=2;y++) for(int x=-1;x<=2;x++) out+=pixel(a,w,p.x+x,p.y+y,high)*cubic(x-d.x)*cubic(y-d.y);
    // OpenCV's remap returns an integer image before blending.
    return rint(clamp(out,0.0f,high?65535.0f:255.0f));
}
kernel void stitch(const device uchar* first [[buffer(0)]],const device uchar* second [[buffer(1)]],
                   const device float* p [[buffer(2)]],const device float* a [[buffer(3)]],
                   const device float* rows [[buffer(4)]],device uchar* output [[buffer(5)]],
                   device atomic_uint* missing [[buffer(6)]],uint2 pos [[thread_position_in_grid]]) {
    int width=int(p[0]),height=width/2; if(pos.x>=uint(width)||pos.y>=uint(height))return;
    bool high=p[1]>0,flow=p[2]>0; int sw=int(p[3]),sh=int(p[4]),area=sw*sh;
    float lon=((float(pos.x)+0.5f)/width-0.5f)*2*PI,lat=((float(pos.y)+0.5f)/height-0.5f)*PI;
    float3 ray=mv(p+8,float3(sin(lon)*cos(lat),sin(lat),cos(lon)*cos(lat)));
    float az=atan2(ray.y,ray.x),latitude=asin(clamp(ray.z,-1.0f,1.0f));
    float fx=(az+PI)/(2*PI/sw)-0.5f,fy=(latitude+PI*8/180)/(PI*16/180/sh)-0.5f;
    float offset=flow&&p[5]>0?field(a,area*6+sw*3,int(p[5]),1,1,0,(az+PI)/(2*PI)*p[5]-0.5f,0):0;
    float alpha=smooth(((latitude-offset)/(PI*1.2f/180)+1)/2);
    bool active=abs(latitude-offset)<PI*1.2f/180;
    float taper=1-smooth(abs(latitude)/(PI*8/180));float3 sum=0;float total=0;
    int maskSize=int(p[7]),maskBase=int(p[6])*8;
    float2 coordinates[2];float weights[2]={0,0},eligible[2]={0,0};
    for(int i=0;i<2;i++) {
        float3 direction=ray;
        if(flow && active) {
            float trust=field(a,area*(4+i),sw,sh,1,0,fx,fy);
            float amount=(i==0?1-alpha:alpha)*trust;
            float u=az-field(a,area*i*2,sw,sh,2,0,fx,fy)*(2*PI/sw)*amount;
            float v=latitude-field(a,area*i*2,sw,sh,2,1,fx,fy)*(PI*16/180/sh)*amount;
            direction=float3(cos(u)*cos(v),sin(u)*cos(v),sin(v));
        }
        float3 local=i==0?direction:mtv(p+17,direction);
        float weight=flow?(i==0?alpha:1-alpha):clamp((local.z+0.1f)/0.2f,0.0f,1.0f);
        if(weight<=0 && maskSize==0)continue;
        float3 velocity=float3(p[26],p[27],p[28]);if(i)velocity=mtv(p+17,velocity);
        const device float* lens=p+30+i*11;
        float3 uv=projectScan(local,lens,velocity,p[29],rows+i*int(p[6])*4,int(p[6]));
        coordinates[i]=uv.xy;eligible[i]=uv.z;
        if(maskSize>0 && uv.z>0) {
            float2 xy=clamp(uv.xy/(lens[10]-1)*(maskSize-1),0.0f,float(maskSize-1));
            eligible[i]*=field(rows,maskBase+i*maskSize*maskSize,maskSize,maskSize,1,0,xy.x,xy.y);
        }
        weights[i]=weight*eligible[i];
    }
    if(maskSize>0 && weights[0]+weights[1]<=1e-5f) {
        weights[0]=eligible[0];weights[1]=eligible[1];
    }
    for(int i=0;i<2;i++) {
        float weight=weights[i];if(weight<=0)continue;
        float3 warped=sample(i==0?first:second,int(p[40+i*11]),coordinates[i],high);
        if(flow)for(int c=0;c<3;c++)warped[c]*=exp(min((i==0?1.0f:-1.0f)*field(a,area*6,sw,1,3,c,fx,0),0.0f)*taper);
        sum+=warped*weight;total+=weight;
    }
    if(total<=1e-5f)atomic_fetch_add_explicit(missing,1,memory_order_relaxed);
    sum=clamp(sum/max(total,1e-5f),0.0f,high?65535.0f:255.0f);
    int n=(pos.y*width+pos.x)*3;
    if(high){device ushort* out=(device ushort*)output;for(int c=0;c<3;c++)out[n+c]=ushort(rint(sum[c]));}
    else for(int c=0;c<3;c++)output[n+c]=uchar(maskSize>0?rint(sum[c]):sum[c]);
}
