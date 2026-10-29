using System;
using System.IO;
using System.Collections.Generic;
using System.Collections;
using System.Globalization;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

// Community-owned transport worker. The official exporter is discovered and
// loaded at runtime; no Rhino API, executable, or installed copy is modified.
internal static class DirectLinkWorker
{
    private const string Prefix = "INGETRAZO_TM ";
    private const string Version = "0.3.0";
    private static string vendor;
    private static JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = Int32.MaxValue, RecursionLimit = 256 };
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

    public static int Main(string[] args)
    {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length != 1) { Console.Error.WriteLine("Usage: DirectLinkWorker <official-exporter-directory>"); return 2; }
        vendor = Path.GetFullPath(args[0]);
        SetDllDirectory(vendor);
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs ev) {
            if (new AssemblyName(ev.Name).Name == "DatasmithRhino6") return Assembly.LoadFrom(Path.Combine(vendor, "DatasmithRhino6.rhp"));
            return null;
        };
        try { return Run(); }
        catch (Exception ex) { Respond(new Dictionary<string, object>{{"ok",false},{"op","fatal"},{"error",ex.ToString()}}); return 1; }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Run()
    {
        Publisher publisher = null;
        try {
            string line;
            while ((line = Console.ReadLine()) != null) {
                string op = "unknown";
                try {
                    var request = Dict(json.DeserializeObject(line));
                    op = Str(request, "op", "");
                    if (op == "quit") { Respond(new Dictionary<string, object>{{"ok",true},{"op",op}}); break; }
                    Dictionary<string, object> response;
                    if (op == "init") {
                        if (publisher != null) throw new InvalidOperationException("Already initialized; restart worker to change source.");
                        publisher = new Publisher(Str(request,"scene_name","IngeTrazo"),Required(request,"cache_dir"));
                        response = publisher.Info();
                    } else {
                        if (publisher == null) throw new InvalidOperationException("Initialize the worker first.");
                        if (op == "snapshot") response = publisher.Snapshot(Required(request,"snapshot_path"));
                        else if (op == "camera") response = publisher.Camera(Dict(Get(request,"camera",null)),Convert.ToBoolean(Get(request,"write_scene",false),CultureInfo.InvariantCulture));
                        else if (op == "info") response = publisher.Info();
                        else throw new ArgumentException("Unknown operation: " + op);
                    }
                    response["ok"] = true; response["op"] = op;
                    Respond(response);
                } catch (Exception ex) {
                    Respond(new Dictionary<string, object>{{"ok",false},{"op",op},{"error",ex.Message},{"error_type",ex.GetType().Name}});
                }
            }
        } finally { if (publisher != null) publisher.Close(); }
        return 0;
    }

    private static void Respond(object value) { Console.WriteLine(Prefix + json.Serialize(value)); Console.Out.Flush(); }
    private static Dictionary<string,object> Dict(object value) { var d = value as Dictionary<string,object>; if (d == null) throw new ArgumentException("Expected a JSON object."); return d; }
    private static object[] Arr(object value) { var a = value as object[]; if (a != null) return a; var l = value as ArrayList; if (l != null) return l.ToArray(); throw new ArgumentException("Expected a JSON array."); }
    private static object Get(Dictionary<string,object> d, string k, object fallback) { object v; return d.TryGetValue(k,out v) && v != null ? v : fallback; }
    private static string Str(Dictionary<string,object> d, string k, string fallback) { return Convert.ToString(Get(d,k,fallback),CultureInfo.InvariantCulture); }
    private static string Required(Dictionary<string,object> d, string k) { string s=Str(d,k,""); if(String.IsNullOrWhiteSpace(s)) throw new ArgumentException("Missing " + k); return s; }
    private static double Num(object v) { double x=Convert.ToDouble(v,CultureInfo.InvariantCulture); if(Double.IsNaN(x)||Double.IsInfinity(x)) throw new ArgumentException("Non-finite number."); return x; }
    private static double Clamp(double x) { return Math.Max(0,Math.Min(1,x)); }
    private static string Hash(string s) { using(var sha=SHA256.Create()) { return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(s))).Replace("-","").ToLowerInvariant().Substring(0,24); } }
    private static string FileHash(string path) { using(var sha=SHA256.Create()) using(var stream=File.OpenRead(path)) { return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant(); } }
    private static double[] Vector(object raw, int length) { var a=Arr(raw); if(a.Length!=length) throw new ArgumentException("Invalid vector length."); var v=new double[length]; for(int i=0;i<length;i++) v[i]=Num(a[i]); return v; }
    private static double[][] Vectors(object raw,int length) { var a=Arr(raw); var v=new double[a.Length][]; for(int i=0;i<a.Length;i++) v[i]=Vector(a[i],length); return v; }
    private static double[] Cross(double[] a,double[] b) { return new double[]{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
    private static double[] Sub(double[] a,double[] b) { return new double[]{a[0]-b[0],a[1]-b[1],a[2]-b[2]}; }
    private static double Length(double[] a) { return Math.Sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]); }
    private static double[] Unit(double[] a) { double n=Length(a); if(n<1e-14) throw new ArgumentException("Zero normal."); return new double[]{a[0]/n,a[1]/n,a[2]/n}; }

    private sealed class MaterialData
    {
        internal string Id, Name, Texture;
        internal byte[] Color;
        internal double Roughness,Metallic,Specular;
    }
    private sealed class MeshData
    {
        internal string Id,Name,Material;
        internal double[][] Vertices,Normals,UVs;
        internal List<int[]> Triangles = new List<int[]>();
        internal List<double[]> CornerNormals = new List<double[]>();
    }
    private sealed class CameraData
    {
        internal double[] Position,Forward,Up;
        internal double HorizontalFov,Aspect,FocusDistance;
    }
    private sealed class MeshCacheEntry : IDisposable
    {
        internal string Signature,AssetPath;
        internal FDatasmithFacadeMeshElement Element;
        public void Dispose() { if(Element!=null) { Element.Dispose(); Element=null; } }
    }
    private sealed class GeometryData
    {
        internal double[][] Vertices,Normals,UVs;
        internal int[][] Triangles;
    }
    private sealed class BinaryGeometrySource : IDisposable
    {
        private sealed class Range
        {
            internal long Offset;
            internal int Vertices,Triangles;
            internal bool Normals,UVs;
        }
        private FileStream stream;
        private BinaryReader reader;
        private readonly Dictionary<string,Range> ranges=new Dictionary<string,Range>();
        private BinaryGeometrySource() {}
        internal static BinaryGeometrySource Open(Dictionary<string,object> root,string snapshotPath)
        {
            object format=Get(root,"geometry_format",null);
            if(format==null) {
                if(root.ContainsKey("geometry_buffer") || root.ContainsKey("geometry_sha256")) throw new ArgumentException("Binary geometry requires geometry_format.");
                return null;
            }
            if(Convert.ToString(format,CultureInfo.InvariantCulture)!="float32-uint32-le-v1") throw new ArgumentException("Unsupported geometry_format.");
            string file=Required(root,"geometry_buffer");
            if(file=="." || file==".." || Path.IsPathRooted(file) || file.IndexOfAny(new char[]{'/','\\',':'})>=0 || Path.GetFileName(file)!=file)
                throw new ArgumentException("geometry_buffer must be a basename in the snapshot directory.");
            string expected=Required(root,"geometry_sha256");
            if(expected.Length!=64) throw new ArgumentException("geometry_sha256 must contain 64 hexadecimal characters.");
            foreach(char digit in expected) if(!Uri.IsHexDigit(digit)) throw new ArgumentException("Invalid geometry_sha256.");
            var source=new BinaryGeometrySource();
            try {
                string path=Path.Combine(Path.GetDirectoryName(snapshotPath),file);
                source.stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read,65536);
                source.reader=new BinaryReader(source.stream,Encoding.UTF8);
                if(source.stream.Length<16 || Encoding.ASCII.GetString(source.reader.ReadBytes(8))!="IGTMESH1" || source.reader.ReadUInt32()!=1 || source.reader.ReadUInt32()!=0)
                    throw new ArgumentException("Invalid binary geometry header.");
                // Check every range and count before allocating any geometry.
                foreach(object raw in Arr(Get(root,"objects",new object[0]))) {
                    var obj=Dict(raw); string id=Required(obj,"id");
                    if(source.ranges.ContainsKey(id)) throw new ArgumentException("Duplicate object id: "+id);
                    var geometry=Dict(Get(obj,"geometry",null));
                    long offset=Count(geometry,"offset",Int64.MaxValue),vertices=Count(geometry,"vertices",Int32.MaxValue/3),triangles=Count(geometry,"triangles",Int32.MaxValue/3);
                    var range=new Range {Offset=offset,Vertices=(int)vertices,Triangles=(int)triangles,Normals=Flag(geometry,"normals"),UVs=Flag(geometry,"uvs")};
                    long bytes=checked(vertices*(12+(range.Normals?12:0)+(range.UVs?8:0))+triangles*12);
                    if(offset<16 || offset>source.stream.Length || bytes>source.stream.Length-offset)
                        throw new ArgumentException("Binary geometry range is outside the buffer: "+id);
                    source.ranges.Add(id,range);
                }
                source.stream.Position=0;
                string actual;
                using(var hash=SHA256.Create()) actual=BitConverter.ToString(hash.ComputeHash(source.stream)).Replace("-","");
                if(!String.Equals(actual,expected,StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Binary geometry SHA256 mismatch.");
                return source;
            } catch { source.Dispose(); throw; }
        }
        private static long Count(Dictionary<string,object> geometry,string name,long maximum)
        {
            if(!geometry.ContainsKey(name) || geometry[name]==null) throw new ArgumentException("Missing binary geometry "+name);
            if(geometry[name] is bool || geometry[name] is string) throw new ArgumentException("Binary geometry "+name+" must be an integer.");
            double number=Num(geometry[name]);
            if(number<0 || number!=Math.Truncate(number) || number>maximum) throw new ArgumentException("Invalid binary geometry "+name);
            return checked((long)number);
        }
        private static bool Flag(Dictionary<string,object> geometry,string name)
        {
            object value=Get(geometry,name,null);
            if(!(value is bool)) throw new ArgumentException("Binary geometry "+name+" must be boolean.");
            return (bool)value;
        }
        private double[][] ReadVectors(int count,int dimensions)
        {
            var values=new double[count][];
            for(int i=0;i<count;i++) {
                var vector=new double[dimensions];
                for(int j=0;j<dimensions;j++) {
                    float number=reader.ReadSingle();
                    if(Single.IsNaN(number)||Single.IsInfinity(number)) throw new ArgumentException("Binary geometry contains a non-finite float.");
                    vector[j]=number;
                }
                values[i]=vector;
            }
            return values;
        }
        internal GeometryData Read(string id)
        {
            Range range=ranges[id]; stream.Position=range.Offset;
            var data=new GeometryData {Vertices=ReadVectors(range.Vertices,3)};
            if(range.Normals) data.Normals=ReadVectors(range.Vertices,3);
            if(range.UVs) data.UVs=ReadVectors(range.Vertices,2);
            data.Triangles=new int[range.Triangles][];
            for(int i=0;i<range.Triangles;i++) {
                var triangle=new int[3];
                for(int j=0;j<3;j++) {
                    uint index=reader.ReadUInt32();
                    if(index>=range.Vertices) throw new ArgumentException("Binary triangle index is out of range: "+id);
                    triangle[j]=(int)index;
                }
                data.Triangles[i]=triangle;
            }
            return data;
        }
        public void Dispose()
        {
            if(reader!=null) { reader.Dispose();reader=null;stream=null; }
            else if(stream!=null) { stream.Dispose();stream=null; }
        }
    }

    private sealed class Publisher
    {
        private FDatasmithFacadeScene scene;
        private FDatasmithFacadeDirectLink direct;
        private FDatasmithFacadeActorCamera cameraActor;
        private CameraData lastCamera;
        private readonly string label,cache,name;
        private int revision,cameraRevision;
        private bool active,cameraAttached;
        private readonly List<string> warnings = new List<string>();
        private readonly Dictionary<string,MeshCacheEntry> meshCache = new Dictionary<string,MeshCacheEntry>();
        internal Publisher(string sceneName,string directory)
        {
            label = sceneName;
            cache = Path.GetFullPath(directory);
            name = "IngeTrazo_" + Hash(label);
            Directory.CreateDirectory(cache);
            if(!FDatasmithFacadeDirectLink.Init()) throw new InvalidOperationException("Datasmith Direct Link initialization failed.");
            active = true;
            FDatasmithFacadeElement.SetCoordinateSystemType(FDatasmithFacadeElement.ECoordinateSystemType.RightHandedZup);
            FDatasmithFacadeElement.SetWorldUnitScale(100.0f); // source metres -> Unreal centimetres
            scene = new FDatasmithFacadeScene("IngeTrazo","IngeTrazo Community","IngeTrazo Twinmotion Sync",Version);
            ConfigureScene();
            direct = new FDatasmithFacadeDirectLink();
            if(!direct.InitializeForScene(scene)) throw new InvalidOperationException("Could not advertise the IngeTrazo source.");
        }
        private void ConfigureScene()
        {
            scene.SetName(name); scene.SetLabel(label); scene.SetHost("IngeTrazo");
            scene.SetVendor("IngeTrazo Community"); scene.SetProductName("IngeTrazo Twinmotion Sync"); scene.SetProductVersion(Version);
            scene.SetOutputPath(cache); scene.PreExport(); Directory.CreateDirectory(scene.GetAssetsOutputPath());
        }
        internal Dictionary<string,object> Info()
        {
            return new Dictionary<string,object>{{"worker_version",Version},{"scene_name",label},{"cache_dir",cache},{"scene_path",Path.Combine(cache,name+".udatasmith")},
                {"source_advertised",true},{"revision",revision},{"communication_status",FDatasmithFacadeDirectLink.ValidateCommunicationSetup()},
                {"receiver_connection","unverified"},{"camera_sync",false},{"input_axes","right-handed Z-up"},{"input_units","metres"},
                {"camera_updates_supported",true},{"camera_published",lastCamera!=null},{"camera_revision",cameraRevision},{"receiver_camera_sync","unverified"},
                {"mesh_cache_entries",meshCache.Count},
                {"snapshot_buffers_supported",true},
                {"sdk_wrapper",typeof(FDatasmithFacadeScene).Assembly.FullName},{"sdk_directory",vendor}};
        }
        internal Dictionary<string,object> Snapshot(string path)
        {
            var totalClock=Stopwatch.StartNew();
            path = Path.GetFullPath(path);
            var root=Dict(json.DeserializeObject(File.ReadAllText(path,Encoding.UTF8)));
            warnings.Clear();
            bool flipV=Convert.ToBoolean(Get(root,"uv_flip_v",true),CultureInfo.InvariantCulture);
            var mats=ParseMaterials(root,Path.GetDirectoryName(path));
            int skipped=0;
            List<MeshData> meshes;
            using(var geometry=BinaryGeometrySource.Open(root,path)) meshes=ParseMeshes(root,mats,out skipped,geometry);
            object rawCamera=Get(root,"camera",null);
            CameraData nextCamera=rawCamera==null ? lastCamera:ParseCamera(Dict(rawCamera));
            double parseMs=totalClock.Elapsed.TotalMilliseconds;
            var exportClock=Stopwatch.StartNew();
            double hashMs=0;
            // Preserve the root object and Direct Link source handle. Reset also
            // clears scene metadata, so reapply application identity and paths.
            scene.Reset(); cameraAttached=false; ConfigureScene();
            foreach(var m in mats.Values) AddMaterial(m);
            int triangles=0,exported=0,reused=0;
            var retained=new HashSet<string>();
            foreach(var m in meshes) {
                retained.Add(m.Id);
                var hashClock=Stopwatch.StartNew(); string signature=MeshSignature(m,flipV); hashMs+=hashClock.Elapsed.TotalMilliseconds;
                MeshCacheEntry entry;
                if(meshCache.TryGetValue(m.Id,out entry) && entry.Signature==signature && File.Exists(entry.AssetPath)) {
                    reused++;
                    // The SDK's XML writer converts the shared element's file
                    // reference to relative. Reattach a valid absolute asset.
                    entry.Element.SetFile(entry.AssetPath);
                } else {
                    using(var mesh = new FDatasmithFacadeMesh()) {
                mesh.SetName("mesh_"+Hash(m.Id));
                mesh.SetVerticesCount(m.Vertices.Length); mesh.SetFacesCount(m.Triangles.Count);
                mesh.SetUVChannelsCount(1); mesh.SetUVCount(0,m.Vertices.Length);
                for(int i=0;i<m.Vertices.Length;i++) {
                    mesh.SetVertex(i,(float)m.Vertices[i][0],(float)m.Vertices[i][1],(float)m.Vertices[i][2]);
                    double u=m.UVs == null ? 0:m.UVs[i][0], v=m.UVs == null ? 0:m.UVs[i][1];
                    mesh.SetUV(0,i,u,flipV ? 1-v:v);
                }
                for(int i=0;i<m.Triangles.Count;i++) {
                    int[] t=m.Triangles[i]; mesh.SetFace(i,t[0],t[1],t[2],0); mesh.SetFaceSmoothingMask(i,0);
                    mesh.SetFaceUV(i,0,t[0],t[1],t[2]);
                    for(int c=0;c<3;c++) { double[] n=m.CornerNormals[i*3+c]; mesh.SetNormal(i*3+c,(float)n[0],(float)n[1],(float)n[2]); }
                }
                var elem=scene.ExportDatasmithMesh(mesh);
                if(elem == null) throw new InvalidOperationException("Could not export mesh: "+m.Name);
                    if(entry!=null) entry.Dispose();
                    entry=new MeshCacheEntry {Signature=signature,Element=elem,AssetPath=Path.GetFullPath(elem.GetFile())};
                    meshCache[m.Id]=entry; exported++;
                    }
                }
                entry.Element.SetMaterial("mat_"+Hash(m.Material),0); scene.AddMesh(entry.Element);
                using(var actor=new FDatasmithFacadeActorMesh("actor_"+Hash(m.Id))) {
                    actor.SetLabel(m.Name); actor.SetMesh(entry.Element.GetName()); scene.AddActor(actor);
                }
                triangles+=m.Triangles.Count;
            }
            if(nextCamera!=null) ApplyCamera(nextCamera);
            if(!WriteScene()) throw new InvalidOperationException("Could not write Datasmith scene.");
            double exportMs=exportClock.Elapsed.TotalMilliseconds;
            var publishClock=Stopwatch.StartNew();
            if(!direct.UpdateScene(scene)) throw new InvalidOperationException("Could not publish scene snapshot.");
            double publishMs=publishClock.Elapsed.TotalMilliseconds;
            var removed=new List<string>(); foreach(string key in meshCache.Keys) if(!retained.Contains(key)) removed.Add(key);
            foreach(string key in removed) { meshCache[key].Dispose(); meshCache.Remove(key); }
            if(nextCamera!=null) { lastCamera=nextCamera; cameraRevision++; }
            revision++;
            var response=Info(); response["objects"]=meshes.Count; response["triangles"]=triangles; response["materials"]=mats.Count;
            response["skipped_degenerate_triangles"]=skipped; response["warnings"]=warnings.ToArray(); response["uv_flip_v"]=flipV;
            response["published"]=true;
            response["mesh_exported"]=exported; response["mesh_reused"]=reused; response["mesh_cache_removed"]=removed.Count;
            response["snapshot_parse_ms"]=parseMs; response["snapshot_export_ms"]=exportMs;
            response["snapshot_publish_ms"]=publishMs; response["snapshot_total_ms"]=totalClock.Elapsed.TotalMilliseconds;
            response["mesh_hash_ms"]=hashMs;
            return response;
        }
        internal Dictionary<string,object> Camera(Dictionary<string,object> input,bool writeScene)
        {
            var totalClock=Stopwatch.StartNew();
            // Validate every projection and orientation value before touching
            // the retained actor or publishing a new Direct Link snapshot.
            CameraData next=ParseCamera(input);
            ApplyCamera(next);
            if(writeScene && !WriteScene()) throw new InvalidOperationException("Could not write camera scene.");
            var publishClock=Stopwatch.StartNew();
            if(!direct.UpdateScene(scene)) throw new InvalidOperationException("Could not publish camera snapshot.");
            double publishMs=publishClock.Elapsed.TotalMilliseconds;
            lastCamera=next; cameraRevision++;
            var response=Info(); response["published"]=true; response["scene_written"]=writeScene;
            response["cameraPublish_ms"]=publishMs; response["camera_total_ms"]=totalClock.Elapsed.TotalMilliseconds;
            return response;
        }
        private static string MeshSignature(MeshData mesh,bool flipV)
        {
            // Only the emitted geometry participates. Material assignments and
            // labels live on scene elements and can change without mesh IO.
            // Stream directly into SHA256 rather than duplicating large buffers.
            using(var hash=SHA256.Create()) {
                using(var crypto=new CryptoStream(Stream.Null,hash,CryptoStreamMode.Write))
                using(var buffered=new BufferedStream(crypto,65536))
                using(var writer=new BinaryWriter(buffered)) {
                    writer.Write(1); writer.Write(flipV);
                    writer.Write(mesh.Vertices.Length);
                    foreach(var vertex in mesh.Vertices) foreach(double value in vertex) writer.Write(value);
                    writer.Write(mesh.Triangles.Count);
                    foreach(var triangle in mesh.Triangles) foreach(int value in triangle) writer.Write(value);
                    writer.Write(mesh.CornerNormals.Count);
                    foreach(var normal in mesh.CornerNormals) foreach(double value in normal) writer.Write(value);
                    writer.Write(mesh.UVs!=null);
                    if(mesh.UVs!=null) foreach(var uv in mesh.UVs) { writer.Write(uv[0]); writer.Write(flipV ? 1-uv[1]:uv[1]); }
                }
                return BitConverter.ToString(hash.Hash).Replace("-","");
            }
        }
        private bool WriteScene()
        {
            // ExportScene mutates asset references to relative paths. Restore
            // absolute inputs before another export so diagnostic camera XML
            // keeps valid asset links without rebuilding or rewriting meshes.
            for(int i=0;i<scene.GetMeshesCount();i++) using(var mesh=scene.GetMesh(i)) {
                string file=mesh.GetFile(); if(!Path.IsPathRooted(file)) mesh.SetFile(Path.GetFullPath(Path.Combine(cache,file)));
            }
            for(int i=0;i<scene.GetTexturesCount();i++) using(var texture=scene.GetTexture(i)) {
                string file=texture.GetFile(); if(!Path.IsPathRooted(file)) texture.SetFile(Path.GetFullPath(Path.Combine(cache,file)));
            }
            return scene.ExportScene(false);
        }
        private static CameraData ParseCamera(Dictionary<string,object> input)
        {
            if(Convert.ToBoolean(Get(input,"orthographic",false),CultureInfo.InvariantCulture))
                throw new ArgumentException("Orthographic camera sync is not supported; switch IngeTrazo to perspective.");
            var result=new CameraData {Position=Vector(Get(input,"position",null),3),Forward=Vector(Get(input,"forward",null),3),Up=Vector(Get(input,"up",null),3)};
            foreach(double v in result.Position) if(Math.Abs(v)>1e9) throw new ArgumentException("Camera position exceeds supported metre range.");
            double forwardLength=Length(result.Forward),upLength=Length(result.Up);
            if(Double.IsInfinity(forwardLength)||Double.IsInfinity(upLength)||forwardLength<1e-12||upLength<1e-12)
                throw new ArgumentException("Camera forward and up must be finite nonzero vectors.");
            result.Forward=Unit(result.Forward); result.Up=Unit(result.Up);
            if(Length(Cross(result.Forward,result.Up))<1e-6) throw new ArgumentException("Camera forward and up must not be parallel.");
            // Match the SDK's MakeFromXZ orientation while preserving roll.
            double dot=result.Forward[0]*result.Up[0]+result.Forward[1]*result.Up[1]+result.Forward[2]*result.Up[2];
            result.Up=Unit(new double[]{result.Up[0]-dot*result.Forward[0],result.Up[1]-dot*result.Forward[1],result.Up[2]-dot*result.Forward[2]});
            result.HorizontalFov=Num(Get(input,"horizontal_fov",null));
            result.Aspect=Num(Get(input,"aspect",null));
            result.FocusDistance=Num(Get(input,"focus_distance",null));
            if(result.HorizontalFov<=1 || result.HorizontalFov>=179) throw new ArgumentException("Camera horizontal FOV must be between 1 and 179 degrees.");
            if(result.Aspect<0.0001 || result.Aspect>10000) throw new ArgumentException("Camera aspect must be between 0.0001 and 10000.");
            if(result.FocusDistance<=0 || (float)result.FocusDistance<=0 || result.FocusDistance>1e9) throw new ArgumentException("Camera focus distance must be positive, representable as a float, and at most 1000000000 metres.");
            return result;
        }
        private void ApplyCamera(CameraData input)
        {
            if(cameraActor==null) {
                cameraActor=new FDatasmithFacadeActorCamera("ingetrazo_active_view");
                cameraActor.SetLabel("IngeTrazo Active View");
            }
            cameraActor.SetCameraPosition(input.Position[0],input.Position[1],input.Position[2]);
            cameraActor.SetCameraRotation(input.Forward[0],input.Forward[1],input.Forward[2],input.Up[0],input.Up[1],input.Up[2]);
            cameraActor.SetSensorWidth(36.0f); cameraActor.SetAspectRatio((float)input.Aspect);
            cameraActor.SetFocalLength((float)input.HorizontalFov,false);
            cameraActor.SetFocusDistance((float)input.FocusDistance); cameraActor.SetEnableDepthOfField(false);
            if(!cameraAttached) { scene.AddActor(cameraActor); cameraAttached=true; }
        }
        private Dictionary<string,MaterialData> ParseMaterials(Dictionary<string,object> root,string sourceDir)
        {
            var result=new Dictionary<string,MaterialData>();
            foreach(object raw in Arr(Get(root,"materials",new object[0]))) {
                var d=Dict(raw); string id=Required(d,"id"); if(result.ContainsKey(id)) throw new ArgumentException("Duplicate material id: "+id);
                var m=new MaterialData {Id=id,Name=Str(d,"name",id),Color=ParseColor(Get(d,"color","#FFFFFF")),
                    Roughness=Clamp(Num(Get(d,"roughness",0.5))),Metallic=Clamp(Num(Get(d,"metallic",0.0))),Specular=Clamp(Num(Get(d,"specular",0.5)))};
                string texture=Str(d,"diffuse_map","");
                if(texture.Length>0) {
                    texture=Path.GetFullPath(Path.IsPathRooted(texture)?texture:Path.Combine(sourceDir,texture));
                    if(File.Exists(texture)) m.Texture=texture;
                    else warnings.Add("Missing texture; using face color: "+texture);
                }
                result.Add(id,m);
            }
            return result;
        }
        private static byte[] ParseColor(object value)
        {
            string text=value as string;
            if(text != null) {
                text=text.TrimStart('#'); if(text.Length!=6 && text.Length!=8) throw new ArgumentException("Expected #RRGGBB or #RRGGBBAA color.");
                var bytes=new byte[]{255,255,255,255}; for(int i=0;i<text.Length/2;i++) bytes[i]=Byte.Parse(text.Substring(i*2,2),NumberStyles.HexNumber,CultureInfo.InvariantCulture); return bytes;
            }
            var a=Arr(value); if(a.Length!=3 && a.Length!=4) throw new ArgumentException("Invalid color array.");
            var color=new byte[]{255,255,255,255}; for(int i=0;i<a.Length;i++) color[i]=(byte)Math.Round(Clamp(Num(a[i]))*255); return color;
        }
        private List<MeshData> ParseMeshes(Dictionary<string,object> root,Dictionary<string,MaterialData> mats,out int skipped,BinaryGeometrySource binary)
        {
            skipped=0; var result=new List<MeshData>(); var ids=new HashSet<string>();
            foreach(object raw in Arr(Get(root,"objects",new object[0]))) {
                var d=Dict(raw); string id=Required(d,"id"); if(!ids.Add(id)) throw new ArgumentException("Duplicate object id: "+id);
                string material=Str(d,"material_id","default_white");
                if(!mats.ContainsKey(material)) mats[material]=new MaterialData {Id=material,Name="Default White",Color=new byte[]{255,255,255,255},Roughness=0.5,Metallic=0,Specular=0.5};
                var mesh=new MeshData {Id=id,Name=Str(d,"name",id),Material=material};
                IEnumerable<int[]> inputTriangles;
                if(binary!=null) {
                    var geometry=binary.Read(id);
                    mesh.Vertices=geometry.Vertices; mesh.Normals=geometry.Normals; mesh.UVs=geometry.UVs;
                    inputTriangles=geometry.Triangles;
                } else {
                    if(d.ContainsKey("geometry")) throw new ArgumentException("Binary geometry requires geometry_format.");
                    mesh.Vertices=Vectors(Get(d,"vertices",new object[0]),3);
                    object rawNormals=Get(d,"normals",null); if(rawNormals!=null) mesh.Normals=Vectors(rawNormals,3);
                    object rawUVs=Get(d,"uvs",null); if(rawUVs!=null) mesh.UVs=Vectors(rawUVs,2);
                    inputTriangles=LegacyTriangles(d,mesh.Vertices.Length,id);
                }
                if(mesh.Normals!=null && mesh.Normals.Length!=mesh.Vertices.Length) throw new ArgumentException("Normals must have one value per vertex: "+id);
                if(mesh.UVs!=null && mesh.UVs.Length!=mesh.Vertices.Length) throw new ArgumentException("UVs must have one value per vertex: "+id);
                double[] matrix=ReadMatrix(Get(d,"transform",null));
                double a=matrix[0],b=matrix[1],c=matrix[2],e=matrix[4],f=matrix[5],g=matrix[6],i=matrix[8],j=matrix[9],k=matrix[10];
                double det=a*(f*k-g*j)-b*(e*k-g*i)+c*(e*j-f*i);
                if(Math.Abs(det)<1e-14) throw new ArgumentException("Singular object transform: "+id);
                // Cofactor matrix / determinant is inverse-transpose.
                double[] normalMatrix={ (f*k-g*j)/det,(g*i-e*k)/det,(e*j-f*i)/det,
                    (c*j-b*k)/det,(a*k-c*i)/det,(b*i-a*j)/det,(b*g-c*f)/det,(c*e-a*g)/det,(a*f-b*e)/det };
                for(int v=0;v<mesh.Vertices.Length;v++) {
                    double[] p=mesh.Vertices[v]; mesh.Vertices[v]=new double[]{a*p[0]+b*p[1]+c*p[2]+matrix[3],e*p[0]+f*p[1]+g*p[2]+matrix[7],i*p[0]+j*p[1]+k*p[2]+matrix[11]};
                    for(int axis=0;axis<3;axis++) if(Double.IsInfinity(mesh.Vertices[v][axis]) || Math.Abs(mesh.Vertices[v][axis])>1e9) throw new ArgumentException("Object coordinate exceeds supported metre range: "+id);
                    if(mesh.Normals!=null) { double[] n=mesh.Normals[v]; mesh.Normals[v]=new double[]{normalMatrix[0]*n[0]+normalMatrix[1]*n[1]+normalMatrix[2]*n[2],normalMatrix[3]*n[0]+normalMatrix[4]*n[1]+normalMatrix[5]*n[2],normalMatrix[6]*n[0]+normalMatrix[7]*n[1]+normalMatrix[8]*n[2]}; }
                }
                foreach(int[] t in inputTriangles) {
                    if(det<0) { int swap=t[1];t[1]=t[2];t[2]=swap; }
                    double[] cross=Cross(Sub(mesh.Vertices[t[1]],mesh.Vertices[t[0]]),Sub(mesh.Vertices[t[2]],mesh.Vertices[t[0]]));
                    if(Length(cross)<1e-12) { skipped++; continue; }
                    double[] flat=Unit(cross); mesh.Triangles.Add(t);
                    for(int n=0;n<3;n++) mesh.CornerNormals.Add(mesh.Normals == null || Length(mesh.Normals[t[n]])<1e-14 ? flat:Unit(mesh.Normals[t[n]]));
                }
                if(mesh.Triangles.Count>0) result.Add(mesh);
            }
            return result;
        }
        private static IEnumerable<int[]> LegacyTriangles(Dictionary<string,object> input,int vertices,string id)
        {
            foreach(object raw in Arr(Get(input,"triangles",new object[0]))) {
                var values=Vector(raw,3); var triangle=new int[3];
                for(int i=0;i<3;i++) {
                    if(values[i]!=Math.Truncate(values[i]) || values[i]<0 || values[i]>=vertices) throw new ArgumentException("Invalid triangle index: "+id);
                    triangle[i]=(int)values[i];
                }
                yield return triangle;
            }
        }
        private static double[] ReadMatrix(object raw)
        {
            if(raw==null) return new double[]{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
            var values=Arr(raw); double[] m;
            if(values.Length==16) m=Vector(raw,16);
            else if(values.Length==4) { m=new double[16]; for(int r=0;r<4;r++) Array.Copy(Vector(values[r],4),0,m,r*4,4); }
            else throw new ArgumentException("Transform must be a row-major 4x4 matrix.");
            if(Math.Abs(m[12])+Math.Abs(m[13])+Math.Abs(m[14])+Math.Abs(m[15]-1)>1e-10) throw new ArgumentException("Only affine transforms are supported.");
            return m;
        }
        private void AddMaterial(MaterialData m)
        {
            var mat=new FDatasmithFacadeUEPbrMaterial("mat_"+Hash(m.Id)); mat.SetLabel(m.Name); mat.SetTwoSided(true);
            var color=mat.AddMaterialExpressionColor(); color.SetName("Base Color"); color.SetsRGBColor(m.Color[0],m.Color[1],m.Color[2],m.Color[3]);
            if(m.Texture != null) {
                string textures=Path.Combine(cache,"Textures"); Directory.CreateDirectory(textures);
                string copy=Path.Combine(textures,FileHash(m.Texture)+Path.GetExtension(m.Texture).ToLowerInvariant());
                if(!File.Exists(copy)) File.Copy(m.Texture,copy,false);
                var tex=new FDatasmithFacadeTexture("tex_"+Hash(m.Id)); tex.SetLabel(m.Name+" Texture"); tex.SetFile(copy);
                tex.SetTextureMode(FDatasmithFacadeTexture.ETextureMode.Diffuse); tex.SetSRGB(FDatasmithFacadeTexture.EColorSpace.sRGB); scene.AddTexture(tex);
                var texture=mat.AddMaterialExpressionTexture(); texture.SetName("Base Color Texture"); texture.SetTexturePathName(tex.GetName());
                if(m.Color[0]==255 && m.Color[1]==255 && m.Color[2]==255) texture.ConnectExpression(mat.GetBaseColor());
                else { var multiply=mat.AddMaterialExpressionGeneric(); multiply.SetExpressionName("Multiply"); texture.ConnectExpression(multiply.GetInput(0)); color.ConnectExpression(multiply.GetInput(1)); multiply.ConnectExpression(mat.GetBaseColor()); }
                texture.Dispose(); tex.Dispose();
            } else color.ConnectExpression(mat.GetBaseColor());
            var rough=mat.AddMaterialExpressionScalar(); rough.SetScalar((float)m.Roughness); rough.ConnectExpression(mat.GetRoughness());
            var metallic=mat.AddMaterialExpressionScalar(); metallic.SetScalar((float)m.Metallic); metallic.ConnectExpression(mat.GetMetallic());
            var specular=mat.AddMaterialExpressionScalar(); specular.SetScalar((float)m.Specular); specular.ConnectExpression(mat.GetSpecular());
            scene.AddMaterial(mat); color.Dispose(); rough.Dispose(); metallic.Dispose(); specular.Dispose(); mat.Dispose();
        }
        internal void Close()
        {
            if(!active) return; active=false;
            if(direct!=null) { direct.CloseCurrentSource(); direct.Dispose(); direct=null; }
            if(scene!=null) { scene.Dispose();scene=null; }
            foreach(var entry in meshCache.Values) entry.Dispose(); meshCache.Clear();
            if(cameraActor!=null) { cameraActor.Dispose();cameraActor=null; }
            FDatasmithFacadeDirectLink.Shutdown();
        }
    }
}
